import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog.data.resolve import ResolvedScore
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import analysis
from labcatalog.stats.analysis import CHOICE
from labcatalog.stats.analysis_script import AnalysisData
from labcatalog.stats.cfa import MEASUREMENT, ML, MLR, WLSMV, CfaModel, model_estimator, write_model

MIN_ITEMS = 2
MIN_FACTORS = 2
DATA_FILE = "measurement_data.csv"
SCRIPT_FILE = "measurement.R"
R_FIT = {
    WLSMV: 'ordered = grep("^x", names(d), value = TRUE), estimator = "WLSMV"',
    MLR: 'estimator = "MLR"',
    ML: 'estimator = "ML"',
}
R_MEASURES = {
    WLSMV: '"chisq.scaled", "df.scaled", "pvalue.scaled", "cfi.scaled", "tli.scaled",\n'
    '  "rmsea.scaled", "rmsea.ci.lower.scaled", "rmsea.ci.upper.scaled", "srmr"',
    MLR: '"chisq.scaled", "df.scaled", "pvalue.scaled", "cfi.robust", "tli.robust",\n'
    '  "rmsea.robust", "rmsea.ci.lower.robust", "rmsea.ci.upper.robust", "srmr"',
    ML: '"chisq", "df", "pvalue", "cfi", "tli", "rmsea", "rmsea.ci.lower", "rmsea.ci.upper",\n'
    '  "srmr"',
}
R_SCRIPT = """\
# Measurement model of {title}, written by labcatalog.
# d is the data saved beside this script: the items of each score, reversed where the scale
# says so, for the people of the sample who answered every one of them.
{names}
# Each score is a factor of its items, factors identified by their variances and free to
# correlate (lavaan::cfa); ω of each factor from semTools::compRelSEM.{within}
# Needs the R packages lavaan and semTools; install them once with:
# install.packages(c("lavaan", "semTools"))
d <- read.csv("{data}")
syntax <- "{syntax}"
fit <- lavaan::cfa(syntax, data = d, {fit}, std.lv = TRUE)
summary(fit, fit.measures = TRUE, standardized = TRUE)
print(lavaan::fitMeasures(fit, c({measures})))
solution <- lavaan::standardizedSolution(fit)
# Standardized loadings, then the factor correlations with their 95% CIs.
print(solution[solution$op == "=~", ])
print(solution[solution$op == "~~" & solution$lhs != solution$rhs, ])
{omega}"""


@dataclass
class Plan:
    model: CfaModel | None
    labels: dict[str, str]
    # Whether every item has answer options, so WLSMV can treat them as ordered.
    ordinal: bool
    problem: str | None = None
    # The study's 0/1 columns, by label, when the sample pools studies.
    covariates: dict[str, str] = field(default_factory=dict)


def part_scores(result: CatalogResult, key: str) -> list[ResolvedScore]:
    # The score in each file of a pooled key, or in its one file.
    by_key = {s.key: s for s in result.catalog.scores}
    return [by_key[analysis.part_key(key, name)] for name in analysis.parts(key)]


def offered(result: CatalogResult, choices: dict[str, str]) -> dict[str, str]:
    # Scores of two or more items, each a possible factor.
    keys = {s.key for s in result.catalog.scores}
    return {
        k: label
        for k, label in choices.items()
        if analysis.first_key(k) in keys
        and all(len(s.columns) >= MIN_ITEMS for s in part_scores(result, k))
    }


def ordinal(result: CatalogResult, keys: list[str]) -> bool:
    for key in keys:
        for score in part_scores(result, key):
            types = {v.column: v.type for v in result.catalog.variables_for(score.dataset)}
            if any(types.get(c) != CHOICE for c in score.columns):
                return False
    return True


def plan(result: CatalogResult, sample: analysis.Sample, keys: list[str]) -> Plan:
    data = AnalysisData(result, sample)
    variables = {k: data.score(k, items=True) for k in keys}
    labels = {k: v.label for k, v in variables.items()}
    found = Plan(None, labels, ordinal(result, keys))
    if len(keys) < MIN_FACTORS:
        found.problem = "Pick two or more scores, each with two or more items."
        return found
    owner: dict[str, str] = {}
    for key, v in variables.items():
        for item in v.items:
            if item in owner:
                found.problem = (
                    f"{labels[owner[item]]} and {labels[key]} share items, such as {item}; a "
                    "factor needs items of its own, so pick scores that do not overlap, such as "
                    "the subscales without their total."
                )
                return found
            owner[item] = key
    # Pooled studies predict every factor, so the factor correlations are within studies.
    if analysis.pooling(result, sample.datasets):
        found.covariates = {v.column: v.label for v in data.study_dummies()}
    columns = list(owner) + list(found.covariates)
    items = data.frame()[columns].dropna()
    datasets = ", ".join(
        dict.fromkeys(d for v in variables.values() for d in v.dataset.split(analysis.POOL))
    )
    factors = {k: v.items for k, v in variables.items()}
    found.model = CfaModel(
        "", datasets, MEASUREMENT, factors, items.reset_index(drop=True), list(found.covariates)
    )
    return found


def script_files(
    model: CfaModel, estimator: str, labels: dict[str, str], title: str
) -> dict[str, str]:
    # The model's data and an R script that fits it the way cfa.R does.
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        name, original = write_model(folder, 1, model, estimator)
        data = (folder / f"{name}.csv").read_text(encoding="utf-8")
        entry = pd.read_csv(folder / "models.csv", keep_default_na=False).iloc[0]
    used = model_estimator(model, estimator)
    names = "\n".join(
        f"#   {short}: {labels.get(original[short], original[short])}"
        for short in original
        if short.startswith("f")
    )
    names += "\n" + "\n".join(
        f"#   {short}: {original[short]}" for short in original if short.startswith("x")
    )
    covariates = [short for short in original if short.startswith("c")]
    names += "".join(f"\n#   {short}: {labels[original[short]]}" for short in covariates)
    within = (
        f"\n# Every factor is regressed on the study ({', '.join(covariates)}), so the "
        "factor\n# correlations are within studies."
        if covariates
        else ""
    )
    omega = (
        "# semTools' ω takes no covariates, so it comes from the factors fitted without the study.\n"
        f'alone <- lavaan::cfa("{entry["omega_syntax"]}", data = d, {R_FIT[used]}, std.lv = TRUE)\n'
        "print(semTools::compRelSEM(alone))\n"
        if covariates
        else "print(semTools::compRelSEM(fit))\n"
    )
    script = R_SCRIPT.format(
        title=title,
        names=names,
        within=within,
        omega=omega,
        data=DATA_FILE,
        syntax=entry["syntax"],
        fit=R_FIT[used],
        measures=R_MEASURES[used],
    )
    return {DATA_FILE: data, SCRIPT_FILE: script}
