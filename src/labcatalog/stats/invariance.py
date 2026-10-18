import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog.config import FreedParameter
from labcatalog.data.resolve import Catalog, ResolvedScore
from labcatalog.data.scoring import scorable, score_items
from labcatalog.project import Project
from labcatalog.schema import Instrument, Score
from labcatalog.sources import LoadedDataset
from labcatalog.stats.cfa import FIT, MIN_ITEMS, ML, MLR, ONE_FACTOR, SUBSCALES, WLSMV, is_total
from labcatalog.stats.link import link
from labcatalog.stats.rbridge import run_r
from labcatalog.stats.summary import wave_order

R_SCRIPT = Path(__file__).parent / "invariance.R"
STEPS = ("configural", "thresholds", "metric", "scalar")
R_NAME = re.compile(r"\b[xf]\d+(_t\d+)?\b")
WAVES = "waves"
REPORTERS = "reporters"
GROUP_COLUMN = "g"
# The parameters each step holds equal, as the user frees them.
STEP_PARAMETER = {"thresholds": "threshold", "metric": "loading", "scalar": "intercept"}


@dataclass
class InvarianceModel:
    study: str
    # The reporter of every occasion; empty across reporters.
    reporter: str
    instrument_id: str
    kind: str
    # Score id to the item ids that load on it.
    factors: dict[str, list[str]]
    # Occasion (a wave, a reporter or a group) to its reversed items, only people who answered
    # them all; across waves and reporters the index pairs the same person.
    occasions: dict[str, pd.DataFrame]
    # waves, reporters, or the grouping item as instrument.item.
    across: str = WAVES
    # The wave of every occasion; empty across waves.
    wave: str = ""
    freed: list[FreedParameter] = field(default_factory=list)
    # Groups too small to fit, with their sizes.
    left_out: dict[str, int] = field(default_factory=dict)


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
    across: str = WAVES
    wave: str = ""
    freed: list[FreedParameter] = field(default_factory=list)
    estimator: str = WLSMV


@dataclass
class ScoreTest:
    item: str
    parameter: str
    chisq: float | None
    df: float | None
    p: float | None


def is_grouped(across: str) -> bool:
    return across not in (WAVES, REPORTERS)


def occasion_name(across: str, occasion: str) -> str:
    return f"wave {occasion}" if across == WAVES else occasion


def build_models(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[InvarianceModel]:
    return wave_models(project, catalog, datasets) + reporter_models(project, catalog, datasets)


def scorable_scores(
    catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> dict[tuple[str, str, str, str], dict[str, dict[str, ResolvedScore]]]:
    # (study, wave, reporter, instrument) -> dataset -> scorable scores
    found: dict[tuple[str, str, str, str], dict[str, dict[str, ResolvedScore]]] = {}
    for score in catalog.scores:
        loaded = datasets[score.dataset]
        if scorable(loaded, score):
            config = loaded.config
            key = (config.study, config.wave, config.reporter, score.instrument_id)
            found.setdefault(key, {}).setdefault(score.dataset, {})[score.score_id] = score
    return found


def wave_models(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[InvarianceModel]:
    by_wave: dict[tuple[str, str, str], dict[str, dict[str, dict[str, ResolvedScore]]]] = {}
    for (study, wave, reporter, instrument_id), found in scorable_scores(catalog, datasets).items():
        by_wave.setdefault((study, reporter, instrument_id), {})[wave] = found
    models = []
    for (study, reporter, instrument_id), waves in by_wave.items():
        instrument = project.instruments[instrument_id]
        for kind, members in factor_sets(instrument):
            factors = {s.id: list(s.items) for s in members}
            occasions = {}
            for wave in sorted(waves, key=wave_order):
                frame = by_person(datasets, waves[wave], factors, by_id(datasets, waves[wave]))
                if frame is not None and len(frame):
                    occasions[wave] = frame
            if len(occasions) >= 2:
                model = InvarianceModel(study, reporter, instrument_id, kind, factors, occasions)
                models.append(with_freed(project, model))
    return models


def reporter_models(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[InvarianceModel]:
    # The reporters of one wave pair through their group, as stats.correlate_by says.
    correlate_by = project.config.stats.correlate_by
    if correlate_by in ("id", "none"):
        return []
    by_reporter: dict[tuple[str, str, str], dict[str, dict[str, dict[str, ResolvedScore]]]] = {}
    for (study, wave, reporter, instrument_id), found in scorable_scores(catalog, datasets).items():
        by_reporter.setdefault((study, wave, instrument_id), {})[reporter] = found
    models = []
    for (study, wave, instrument_id), reporters in by_reporter.items():
        if len(reporters) < 2:
            continue
        names = [name for found in reporters.values() for name in found]
        rows = link(datasets, names, correlate_by).rows
        instrument = project.instruments[instrument_id]
        for kind, members in factor_sets(instrument):
            factors = {s.id: list(s.items) for s in members}
            occasions = {}
            for reporter, found in reporters.items():
                frame = by_person(datasets, found, factors, {n: rows[n] for n in found})
                if frame is not None and len(frame):
                    occasions[reporter] = frame
            if len(occasions) >= 2:
                model = InvarianceModel(
                    study, "", instrument_id, kind, factors, occasions, REPORTERS, wave
                )
                models.append(with_freed(project, model))
    return models


def with_freed(project: Project, model: InvarianceModel) -> InvarianceModel:
    items = {item for members in model.factors.values() for item in members}
    model.freed = [
        f
        for f in project.config.stats.invariance_free
        if (f.instrument, f.across) == (model.instrument_id, model.across) and f.item in items
    ]
    return model


def factor_sets(instrument: Instrument) -> list[tuple[str, list[Score]]]:
    # The measurement model only: subscales together, or each score on its own.
    subscales = [s for s in instrument.scores if not is_total(instrument, s.id)]
    if len(subscales) >= 2:
        return [(SUBSCALES, subscales)]
    return [(ONE_FACTOR, [s]) for s in instrument.scores if len(s.items) >= MIN_ITEMS]


def by_id(
    datasets: dict[str, LoadedDataset], by_dataset: dict[str, dict[str, ResolvedScore]]
) -> dict[str, pd.Series]:
    # Each row of a file under its participant ID.
    rows = {}
    for name in by_dataset:
        ids = datasets[name].frame[datasets[name].id_column]
        rows[name] = pd.Series(range(len(ids)), index=ids.to_numpy())
    return rows


def dataset_items(
    loaded: LoadedDataset, scores: dict[str, ResolvedScore], factors: dict[str, list[str]]
) -> pd.DataFrame:
    # The reversed items of the factors, one row per row of the file.
    parts = []
    for score_id, members in factors.items():
        part = score_items(loaded, scores[score_id])
        # A scorable score's columns follow its items in order.
        part.columns = members
        parts.append(part)
    frame = pd.concat(parts, axis=1)
    items = list(dict.fromkeys(item for members in factors.values() for item in members))
    return frame.loc[:, ~frame.columns.duplicated()][items]


def by_person(
    datasets: dict[str, LoadedDataset],
    by_dataset: dict[str, dict[str, ResolvedScore]],
    factors: dict[str, list[str]],
    rows: dict[str, pd.Series],
) -> pd.DataFrame | None:
    frames = []
    for dataset, scores in by_dataset.items():
        if set(factors) <= set(scores):
            items = dataset_items(datasets[dataset], scores, factors)
            frames.append(items.iloc[rows[dataset].to_numpy()].set_axis(rows[dataset].index))
    if not frames:
        return None
    frame = pd.concat(frames)
    # A person who repeats within an occasion cannot say which answers are theirs.
    return frame[~frame.index.duplicated(keep=False) & frame.index.notna()].dropna()


def fit_models(
    models: list[InvarianceModel], rscript: str, estimator: str = WLSMV
) -> list[InvarianceTest]:
    # Only ordered items have thresholds that every occasion must share.
    gaps = [unchosen_options(model) if estimator == WLSMV else None for model in models]
    ready = [model for model, gap in zip(models, gaps, strict=True) if gap is None]
    tested = iter(fit_in_r(ready, rscript, estimator))
    found = [
        next(tested) if gap is None else new_test(model, problem=gap)
        for model, gap in zip(models, gaps, strict=True)
    ]
    for test in found:
        test.estimator = estimator
    return found


def unchosen_options(model: InvarianceModel) -> str | None:
    # lavaan numbers an item's categories from the values it sees, so every occasion needs the same.
    gaps = []
    for item in next(iter(model.occasions.values())).columns:
        chosen = {key: set(frame[item]) for key, frame in model.occasions.items()}
        every = set().union(*chosen.values())
        for key, values in chosen.items():
            if values != every:
                options = ", ".join(f"{v:g}" for v in sorted(every - values))
                gaps.append(f"{item} in {occasion_name(model.across, key)} ({options})")
    if not gaps:
        return None
    word = "wave" if model.across == WAVES else "reporter" if model.across == REPORTERS else "group"
    return (
        f"Thresholds can only be held equal when every {word} uses the same options, and nobody "
        f"chose these options that were chosen elsewhere: {'; '.join(gaps)}. Merging rarely "
        "chosen options would make the test possible."
    )


def fit_in_r(models: list[InvarianceModel], rscript: str, estimator: str) -> list[InvarianceTest]:
    if not models:
        return []
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        names = [write_model(folder, n, model, estimator) for n, model in enumerate(models, 1)]
        results = run_script(folder, rscript, estimator, "steps")
    return [read_test(model, name, results) for model, name in zip(models, names, strict=True)]


def score_tests(
    model: InvarianceModel, step: str, rscript: str, estimator: str = WLSMV
) -> list[ScoreTest]:
    # For each item, the test of freeing what the step holds equal for it.
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        _, original = write_model(folder, 1, model, estimator, step)
        results = run_script(folder, rscript, estimator, "score")
    problem = results[results["what"] == "problem"]
    if len(problem):
        raise ValueError(readable(problem["message"].iloc[0], original))
    found: dict[str, dict[str, float | None]] = {}
    for row in results[results["what"] == "score"].itertuples():
        found.setdefault(row.item, {})[row.message] = None if pd.isna(row.value) else row.value
    items = item_names(model)
    return [
        ScoreTest(items[stem], STEP_PARAMETER[step], v.get("chisq"), v.get("df"), v.get("p"))
        for stem, v in found.items()
    ]


def run_script(folder: Path, rscript: str, estimator: str, action: str) -> pd.DataFrame:
    run_r(rscript, [str(R_SCRIPT), str(folder), estimator, action])
    return pd.read_csv(folder / "results.csv", keep_default_na=False, na_values={"value": ["NA"]})


def item_names(model: InvarianceModel) -> dict[str, str]:
    items = next(iter(model.occasions.values())).columns
    return {f"x{i}": item for i, item in enumerate(items, start=1)}


def partial(model: InvarianceModel, estimator: str) -> list[str]:
    # The freed parameters in lavaan syntax, named as on every occasion at once.
    stems = {item: stem for stem, item in item_names(model).items()}
    found = []
    for f in model.freed:
        x = stems[f.item]
        if f.parameter == "loading":
            found += [
                f"f{j} =~ {x}"
                for j, members in enumerate(model.factors.values(), start=1)
                if f.item in members
            ]
        elif f.parameter == "intercept":
            found.append(f"{x} ~1")
        elif estimator == WLSMV:
            values = set().union(*(set(frame[f.item]) for frame in model.occasions.values()))
            found += [f"{x} | t{k}" for k in range(1, len(values))]
    return found


def write_model(
    folder: Path, n: int, model: InvarianceModel, estimator: str, step: str = ""
) -> tuple[str, dict[str, str]]:
    items = list(next(iter(model.occasions.values())).columns)
    columns = {item: f"x{i}" for i, item in enumerate(items, start=1)}
    grouped = is_grouped(model.across)
    if grouped:
        data, original = stacked(model, columns)
        occasions = [""]
    else:
        data, original = side_by_side(model, columns)
        occasions = [f"_t{t}" for t in range(1, len(model.occasions) + 1)]
    for j, score in enumerate(model.factors, start=1):
        original[f"f{j}"] = score
        for t, key in enumerate(model.occasions, start=1):
            original[f"f{j}_t{t}"] = f"{score} ({occasion_name(model.across, key)})"
    original |= {x: item for item, x in columns.items()}
    syntax = "; ".join(
        f"f{j}{suffix} =~ " + " + ".join(f"{columns[item]}{suffix}" for item in members)
        for suffix in occasions
        for j, members in enumerate(model.factors.values(), start=1)
    )
    name = f"m{n}"
    data.to_csv(folder / f"{name}.csv", index=False, float_format="%g")
    entry = {
        "model": name,
        "data": f"{name}.csv",
        "syntax": syntax,
        "partial": "; ".join(partial(model, estimator)),
        "group": GROUP_COLUMN if grouped else "",
        "step": step,
    }
    path = folder / "models.csv"
    pd.DataFrame([entry]).to_csv(path, mode="a", header=not path.exists(), index=False)
    return name, original


SCRIPT_DATA = "invariance_data.csv"
SCRIPT_FILE = "invariance.R"
R_STEPS = {
    WLSMV: (
        'list(configural = "", thresholds = "thresholds",\n'
        '              metric = c("thresholds", "loadings"),\n'
        '              scalar = c("thresholds", "loadings", "intercepts"))',
        '"chisq.scaled", "df.scaled", "pvalue.scaled", "cfi.scaled", "tli.scaled", '
        '"rmsea.scaled", "srmr"',
        'ordered = items, estimator = "WLSMV", missing = "pairwise",\n'
        '                   parameterization = "theta", ID.cat = "Wu.Estabrook.2016"',
    ),
    MLR: (
        'list(configural = "", metric = "loadings", scalar = c("loadings", "intercepts"))',
        '"chisq.scaled", "df.scaled", "pvalue.scaled", "cfi.robust", "tli.robust", '
        '"rmsea.robust", "srmr"',
        'estimator = "MLR", missing = "ml"',
    ),
    ML: (
        'list(configural = "", metric = "loadings", scalar = c("loadings", "intercepts"))',
        '"chisq", "df", "pvalue", "cfi", "tli", "rmsea", "srmr"',
        'estimator = "ML", missing = "ml"',
    ),
}
R_INVARIANCE = """\
# Measurement invariance of {title}, written by labcatalog.
# d is the data saved beside this script, the items reversed where the scale says so:
{names}
# Each step holds more parameters equal (semTools::measEq.syntax, factors identified by their
# variances), and lavTestLRT compares each step with the one before it. {method}
# Needs the R packages lavaan and semTools; install them once with:
# install.packages(c("lavaan", "semTools"))
d <- read.csv("{data}")
syntax <- "{syntax}"
items <- setdiff(names(d), "{group}")
steps <- {steps}
{across}fits <- list()
for (step in names(steps)) {{
  fits[[step]] <- semTools::measEq.syntax(
    configural.model = syntax, data = d, ID.fac = "std.lv", return.fit = TRUE,
    {options},
    {equal}
  )
  cat("\\n", step, "\\n")
  print(lavaan::fitMeasures(fits[[step]], c({measures})))
}}
print(do.call(lavaan::lavTestLRT, unname(fits)))
"""
R_LONG_NAMES = """\
# The same item or factor on each occasion differs only in its _t<occasion> ending.
stem <- function(names) sub("_t[0-9]+$", "", names)
by_stem <- function(names) split(names, stem(names))
"""
METHODS = {
    WLSMV: "The items are ordered categories (WLSMV, theta parameterization, Wu and Estabrook's "
    "identification).",
    MLR: "The items are continuous, with robust ML (MLR) and everyone's available answers.",
    ML: "The items are continuous, with ML and everyone's available answers.",
}


def script_files(model: InvarianceModel, estimator: str, title: str) -> dict[str, str]:
    # One model's data and an R script that fits its steps the way invariance.R does.
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        name, original = write_model(folder, 1, model, estimator)
        data = (folder / f"{name}.csv").read_text(encoding="utf-8")
        entry = pd.read_csv(folder / "models.csv", keep_default_na=False).iloc[0]
    steps, measures, options = R_STEPS[estimator]
    freed = [f'"{p}"' for p in entry["partial"].split("; ") if p]
    free = f"c({', '.join(freed)})" if freed else '""'
    group = entry["group"]
    if group:
        across = ""
        equal = f'group = "{group}", group.equal = steps[[step]], group.partial = {free}'
    else:
        across = R_LONG_NAMES
        equal = (
            'longFacNames = by_stem(lavaan::lavNames(syntax, "lv")),\n'
            "    longIndNames = by_stem(items), long.equal = steps[[step]],\n"
            f"    long.partial = {free}"
        )
    shorts = dict.fromkeys(m.group(0) for m in R_NAME.finditer(entry["syntax"]))
    names = "\n".join(f"#   {short}: {original[short]}" for short in shorts if short in original)
    if group:
        names += f"\n#   {group}: the group"
    script = R_INVARIANCE.format(
        title=title,
        names=names,
        method=METHODS[estimator],
        data=SCRIPT_DATA,
        syntax=entry["syntax"],
        group=group,
        steps=steps,
        across=across,
        options=options,
        equal=equal,
        measures=measures,
    )
    return {SCRIPT_DATA: data, SCRIPT_FILE: script}


def side_by_side(
    model: InvarianceModel, columns: dict[str, str]
) -> tuple[pd.DataFrame, dict[str, str]]:
    # x<item>_t<occasion> lets R pair the same item across occasions.
    original = {}
    frames = []
    for t, (key, frame) in enumerate(model.occasions.items(), start=1):
        names = {item: f"{x}_t{t}" for item, x in columns.items()}
        original |= {v: f"{k} ({occasion_name(model.across, key)})" for k, v in names.items()}
        frames.append(frame.rename(columns=names))
    return pd.concat(frames, axis=1, join="outer"), original


def stacked(model: InvarianceModel, columns: dict[str, str]) -> tuple[pd.DataFrame, dict[str, str]]:
    frames = [
        frame.rename(columns=columns).assign(**{GROUP_COLUMN: key})
        for key, frame in model.occasions.items()
    ]
    return pd.concat(frames, ignore_index=True), {}


def read_test(
    model: InvarianceModel, named: tuple[str, dict[str, str]], results: pd.DataFrame
) -> InvarianceTest:
    name, original = named
    rows = results[results["model"] == name]
    test = new_test(model)
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
    # Continuous items have no thresholds step.
    test.steps = [s for s in steps.values() if s.fit or s.problem]
    return test


def new_test(model: InvarianceModel, problem: str | None = None) -> InvarianceTest:
    n = {key: len(frame) for key, frame in model.occasions.items()}
    return InvarianceTest(
        model.study,
        model.reporter,
        model.instrument_id,
        model.kind,
        model.factors,
        n,
        problem=problem,
        across=model.across,
        wave=model.wave,
        freed=list(model.freed),
    )


def readable(message: str, original: dict[str, str]) -> str:
    return R_NAME.sub(lambda m: original.get(m.group(), m.group()), message)
