import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import semopy

from labcatalog.data.resolve import Catalog, ResolvedScore
from labcatalog.data.scoring import scorable, score_items
from labcatalog.project import Project
from labcatalog.schema import Instrument
from labcatalog.sources import LoadedDataset
from labcatalog.stats.rbridge import run_r

R_SCRIPT = Path(__file__).parent / "cfa.R"
MIN_ITEMS = 3
SUBSCALES = "subscales"
ONE_FACTOR = "one factor"
R = "R"
PYTHON = "Python"
IMPROPER = "improper solution (a negative variance or a correlation above 1)"
WLSMV = "wlsmv"
ML = "ml"
# lavaan's names for the scaled (WLSMV) and plain (ML) fit measures.
FIT = {
    "chisq.scaled": "chisq",
    "df.scaled": "df",
    "pvalue.scaled": "p",
    "cfi.scaled": "cfi",
    "tli.scaled": "tli",
    "rmsea.scaled": "rmsea",
    "chisq": "chisq",
    "df": "df",
    "pvalue": "p",
    "cfi": "cfi",
    "tli": "tli",
    "rmsea": "rmsea",
    "srmr": "srmr",
}


@dataclass
class CfaModel:
    instrument_id: str
    dataset: str
    kind: str
    # Score id to the columns that load on it.
    factors: dict[str, list[str]]
    data: pd.DataFrame


@dataclass
class CfaFit:
    instrument_id: str
    dataset: str
    kind: str
    factors: dict[str, list[str]]
    n: int
    fit: dict[str, float | None] = field(default_factory=dict)
    loadings: dict[tuple[str, str], float] = field(default_factory=dict)
    omega: dict[str, float] = field(default_factory=dict)
    problem: str | None = None
    engine: str = R
    estimator: str = WLSMV


def is_total(instrument: Instrument, score_id: str) -> bool:
    # The total covers every item the instrument's scores use, as on the charts.
    used = set().union(*(set(s.items) for s in instrument.scores))
    return next(set(s.items) == used for s in instrument.scores if s.id == score_id)


def build_models(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[CfaModel]:
    groups: dict[tuple[str, str], list[ResolvedScore]] = {}
    for score in catalog.scores:
        if scorable(datasets[score.dataset], score):
            groups.setdefault((score.instrument_id, score.dataset), []).append(score)
    models = []
    for (instrument_id, dataset), scores in groups.items():
        instrument = project.instruments[instrument_id]
        subscales = [s for s in scores if not is_total(instrument, s.score_id)]
        if len(subscales) >= 2:
            sets = [(SUBSCALES, subscales)]
            sets += [(ONE_FACTOR, [s]) for s in scores if is_total(instrument, s.score_id)]
        else:
            sets = [(ONE_FACTOR, [s]) for s in scores]
        for kind, members in sets:
            if kind == ONE_FACTOR and len(members[0].columns) < MIN_ITEMS:
                continue
            frames = [score_items(datasets[dataset], s) for s in members]
            data = pd.concat(frames, axis=1)
            data = data.loc[:, ~data.columns.duplicated()].dropna()
            factors = {s.score_id: s.columns for s in members}
            models.append(CfaModel(instrument_id, dataset, kind, factors, data))
    return models


def fit_models(models: list[CfaModel], rscript: str | None, estimator: str = WLSMV) -> list[CfaFit]:
    # lavaan in R when there is an Rscript, otherwise semopy here, which has ML only.
    if not rscript:
        return [fit_python(model) for model in models]
    if not models:
        return []
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        names = [write_model(folder, n, model) for n, model in enumerate(models, start=1)]
        run_r(rscript, [str(R_SCRIPT), str(folder), estimator])
        results = pd.read_csv(
            folder / "results.csv", keep_default_na=False, na_values={"value": ["NA"]}
        )
    return [
        read_fit(model, name, results, estimator) for model, name in zip(models, names, strict=True)
    ]


def write_model(folder: Path, n: int, model: CfaModel) -> tuple[str, dict[str, str]]:
    # R and lavaan never rename x1 or f1, so results map back to columns and scores safely.
    columns = list(model.data.columns)
    items = {column: f"x{i}" for i, column in enumerate(columns, start=1)}
    factors = {score: f"f{i}" for i, score in enumerate(model.factors, start=1)}
    syntax = "; ".join(
        f"{factors[score]} =~ {' + '.join(items[c] for c in columns_)}"
        for score, columns_ in model.factors.items()
    )
    name = f"m{n}"
    model.data.set_axis(list(items.values()), axis=1).to_csv(
        folder / f"{name}.csv", index=False, float_format="%g"
    )
    entry = pd.DataFrame([{"model": name, "data": f"{name}.csv", "syntax": syntax}])
    path = folder / "models.csv"
    entry.to_csv(path, mode="a", header=not path.exists(), index=False)
    return name, {**{v: k for k, v in items.items()}, **{v: k for k, v in factors.items()}}


def read_fit(
    model: CfaModel, named: tuple[str, dict[str, str]], results: pd.DataFrame, estimator: str
) -> CfaFit:
    name, original = named
    rows = results[results["model"] == name]
    fit = CfaFit(
        model.instrument_id,
        model.dataset,
        model.kind,
        model.factors,
        len(model.data),
        estimator=estimator,
    )
    problems = rows[rows["what"] == "problem"]
    if len(problems):
        fit.problem = problems["message"].iloc[0]
        return fit
    for row in rows.itertuples():
        if row.what == "fit":
            fit.fit[FIT[row.item]] = None if pd.isna(row.value) else float(row.value)
        elif row.what == "loading":
            fit.loadings[(original[row.factor], original[row.item])] = float(row.value)
        elif row.what == "omega":
            fit.omega[original[row.factor]] = float(row.value)
    return exact(fit)


def exact(fit: CfaFit) -> CfaFit:
    # A just-identified model reproduces the data exactly, so its fit indices say nothing.
    if fit.fit.get("df") == 0:
        fit.fit = {"chisq": None, "df": 0.0}
    return fit


def fit_python(model: CfaModel) -> CfaFit:
    # Items as continuous, maximum likelihood; lavaan's ML gives the same numbers.
    items = {c: f"x{i}" for i, c in enumerate(model.data.columns, start=1)}
    factors = {score: f"f{i}" for i, score in enumerate(model.factors, start=1)}
    original = {v: k for k, v in {**items, **factors}.items()}
    syntax = "\n".join(
        f"{factors[score]} =~ {' + '.join(items[c] for c in columns)}"
        for score, columns in model.factors.items()
    )
    data = model.data.set_axis(list(items.values()), axis=1)
    fit = CfaFit(
        model.instrument_id,
        model.dataset,
        model.kind,
        model.factors,
        len(data),
        engine=PYTHON,
        estimator=ML,
    )
    sem = semopy.Model(syntax)
    # As cfa.R does, a model that fails is reported, and the other models still run.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            solved = sem.fit(data)
            found = sem.inspect(std_est=True)
            stats = semopy.calc_stats(sem).T["Value"]
    except Exception as err:  # noqa: BLE001
        fit.problem = str(err)
        return fit
    if not solved.success:
        fit.problem = "the model did not converge"
        return fit
    estimate = found["Estimate"].astype(float)
    standard = found["Est. Std"].astype(float)
    variances = (found["op"] == "~~") & (found["lval"] == found["rval"])
    if (estimate[variances] < 0).any() or (standard[~variances].abs() > 1).any():
        fit.problem = IMPROPER
        return fit
    fit.fit = {
        "chisq": float(stats["chi2"]),
        "df": float(stats["DoF"]),
        "p": float(stats["chi2 p-value"]),
        # lavaan caps CFI at 1.
        "cfi": min(float(stats["CFI"]), 1.0),
        "tli": float(stats["TLI"]),
        "rmsea": float(stats["RMSEA"]),
        "srmr": None,
    }
    loadings = found[found["op"] == "~"]
    for item, factor, value in zip(
        loadings["lval"], loadings["rval"], standard[loadings.index], strict=True
    ):
        fit.loadings[(original[factor], original[item])] = float(value)
    # semTools' omega: the factor's share of the observed variance of the summed items.
    observed = data.cov(ddof=0)
    for factor in factors.values():
        rows = loadings[loadings["rval"] == factor]
        variance = estimate[(found["lval"] == factor) & (found["rval"] == factor) & variances]
        columns = list(rows["lval"])
        common = estimate[rows.index].sum() ** 2 * float(variance.iloc[0])
        fit.omega[original[factor]] = common / observed.loc[columns, columns].to_numpy().sum()
    return exact(fit)
