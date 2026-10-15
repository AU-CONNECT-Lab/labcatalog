import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog.cfa import FIT, MIN_ITEMS, ONE_FACTOR, SUBSCALES, is_total
from labcatalog.project import Project
from labcatalog.rbridge import run_r
from labcatalog.resolve import Catalog, ResolvedScore
from labcatalog.schema import Instrument, Score
from labcatalog.scoring import scorable, score_items
from labcatalog.sources import LoadedDataset
from labcatalog.stats import wave_order

R_SCRIPT = Path(__file__).parent / "invariance.R"
STEPS = ("configural", "thresholds", "metric", "scalar")
R_NAME = re.compile(r"\b[xf]\d+_t\d+\b")


@dataclass
class InvarianceModel:
    study: str
    reporter: str
    instrument_id: str
    kind: str
    # Score id to the item ids that load on it.
    factors: dict[str, list[str]]
    # Wave to its reversed items by participant ID, only people who answered them all.
    waves: dict[str, pd.DataFrame]


@dataclass
class InvarianceStep:
    step: str
    fit: dict[str, float | None] = field(default_factory=dict)
    # Scaled chi-square difference with the step before.
    chisq_diff: float | None = None
    df_diff: float | None = None
    p_diff: float | None = None
    problem: str | None = None


@dataclass
class InvarianceTest:
    study: str
    reporter: str
    instrument_id: str
    kind: str
    factors: dict[str, list[str]]
    n: dict[str, int]
    steps: list[InvarianceStep] = field(default_factory=list)
    problem: str | None = None


def build_models(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[InvarianceModel]:
    # (study, reporter, instrument) -> wave -> dataset -> scorable scores
    found: dict[tuple[str, str, str], dict[str, dict[str, dict[str, ResolvedScore]]]] = {}
    for score in catalog.scores:
        loaded = datasets[score.dataset]
        if scorable(loaded, score):
            config = loaded.config
            key = (config.study, config.reporter, score.instrument_id)
            by_dataset = found.setdefault(key, {}).setdefault(config.wave, {})
            by_dataset.setdefault(score.dataset, {})[score.score_id] = score
    models = []
    for (study, reporter, instrument_id), by_wave in found.items():
        instrument = project.instruments[instrument_id]
        for kind, members in factor_sets(instrument):
            factors = {s.id: list(s.items) for s in members}
            waves = {}
            for wave in sorted(by_wave, key=wave_order):
                frame = wave_items(datasets, by_wave[wave], factors)
                if frame is not None and len(frame):
                    waves[wave] = frame
            if len(waves) >= 2:
                models.append(
                    InvarianceModel(study, reporter, instrument_id, kind, factors, waves)
                )
    return models


def factor_sets(instrument: Instrument) -> list[tuple[str, list[Score]]]:
    # The measurement model only: subscales together, or each score on its own.
    subscales = [s for s in instrument.scores if not is_total(instrument, s.id)]
    if len(subscales) >= 2:
        return [(SUBSCALES, subscales)]
    return [(ONE_FACTOR, [s]) for s in instrument.scores if len(s.items) >= MIN_ITEMS]


def wave_items(
    datasets: dict[str, LoadedDataset],
    by_dataset: dict[str, dict[str, ResolvedScore]],
    factors: dict[str, list[str]],
) -> pd.DataFrame | None:
    items = list(dict.fromkeys(item for members in factors.values() for item in members))
    frames = []
    for dataset, scores in by_dataset.items():
        if not set(factors) <= set(scores):
            continue
        loaded = datasets[dataset]
        parts = []
        for score_id, members in factors.items():
            part = score_items(loaded, scores[score_id])
            # A scorable score's columns follow its items in order.
            part.columns = members
            parts.append(part)
        frame = pd.concat(parts, axis=1)
        frame = frame.loc[:, ~frame.columns.duplicated()][items]
        frame.index = loaded.frame[loaded.id_column].to_numpy()
        frames.append(frame)
    if not frames:
        return None
    frame = pd.concat(frames)
    # An ID that repeats within a wave cannot say which answers belong to the person.
    return frame[~frame.index.duplicated(keep=False) & frame.index.notna()].dropna()


def fit_models(models: list[InvarianceModel], rscript: str) -> list[InvarianceTest]:
    if not models:
        return []
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        names = [write_model(folder, n, model) for n, model in enumerate(models, start=1)]
        run_r(rscript, [str(R_SCRIPT), str(folder)])
        results = pd.read_csv(
            folder / "results.csv", keep_default_na=False, na_values={"value": ["NA"]}
        )
    return [read_test(model, name, results) for model, name in zip(models, names, strict=True)]


def write_model(folder: Path, n: int, model: InvarianceModel) -> tuple[str, dict[str, str]]:
    # x<item>_t<wave> and f<factor>_t<wave> let R pair the same item or factor across waves.
    items = list(next(iter(model.waves.values())).columns)
    original = {}
    frames = []
    for t, (wave, frame) in enumerate(model.waves.items(), start=1):
        names = {item: f"x{i}_t{t}" for i, item in enumerate(items, start=1)}
        original.update({v: f"{k} (wave {wave})" for k, v in names.items()})
        frames.append(frame.rename(columns=names))
        for j, score in enumerate(model.factors, start=1):
            original[f"f{j}_t{t}"] = f"{score} (wave {wave})"
    syntax = "; ".join(
        f"f{j}_t{t} =~ "
        + " + ".join(f"x{items.index(item) + 1}_t{t}" for item in members)
        for t in range(1, len(model.waves) + 1)
        for j, members in enumerate(model.factors.values(), start=1)
    )
    name = f"m{n}"
    data = pd.concat(frames, axis=1, join="outer")
    data.to_csv(folder / f"{name}.csv", index=False, float_format="%g")
    entry = pd.DataFrame([{"model": name, "data": f"{name}.csv", "syntax": syntax}])
    path = folder / "models.csv"
    entry.to_csv(path, mode="a", header=not path.exists(), index=False)
    return name, original


def read_test(
    model: InvarianceModel, named: tuple[str, dict[str, str]], results: pd.DataFrame
) -> InvarianceTest:
    name, original = named
    rows = results[results["model"] == name]
    test = InvarianceTest(
        model.study,
        model.reporter,
        model.instrument_id,
        model.kind,
        model.factors,
        {wave: len(frame) for wave, frame in model.waves.items()},
    )
    steps = {step: InvarianceStep(step) for step in STEPS}
    for row in rows.itertuples():
        value = None if pd.isna(row.value) else float(row.value)
        if row.what == "problem" and not row.step:
            test.problem = readable(row.message, original)
            return test
        step = steps[row.step]
        if row.what == "problem":
            step.problem = readable(row.message, original)
        elif row.what == "fit":
            step.fit[FIT[row.item]] = value
        elif row.what == "compare":
            setattr(step, row.item, value)
    test.steps = list(steps.values())
    return test


def readable(message: str, original: dict[str, str]) -> str:
    return R_NAME.sub(lambda m: original.get(m.group(), m.group()), message)
