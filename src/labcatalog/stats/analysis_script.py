import contextlib
import io
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from labcatalog import defaults
from labcatalog.data.resolve import ResolvedVariable
from labcatalog.data.scoring import score_items
from labcatalog.pipeline import CatalogResult
from labcatalog.reports.codegen import number
from labcatalog.stats import analysis
from labcatalog.stats.analysis import (
    CHOICE,
    ITEM_PREFIX,
    NUMBER,
    instrument_of,
    item_key,
    item_variable,
    number_items,
)
from labcatalog.stats.cfa import is_total
from labcatalog.stats.rbridge import install_command, package_check, run_r

DATA_FILE = "analysis_data.csv"
PERSON_ID = "id"
SCORE = "score"
WELCH = "welch"
STUDENT = "student"
ANOVA = "anova"
# Welch's and Student's tests read back the same way.
TWO = "two groups"
MIN_GROUP = 2
R = "R"
PYTHON = "Python"

R_HEADER = """\
# {title}
# {sample}
# d is the analysis data saved beside this script: one row per person, scores as labcatalog
# computed them, each score's items reversed where the scale says so, and numbers blank
# where they fall outside the item's range.{packages}
d <- read.csv({path}, check.names = FALSE)
"""
PYTHON_HEADER = """\
# {title}
# {sample}
# d is the analysis data saved beside this script: one row per person, scores as labcatalog
# computed them, each score's items reversed where the scale says so, and numbers blank
# where they fall outside the item's range.
# Needs pandas, pingouin and scipy (pip install pingouin).
import numpy as np
import pandas as pd
import pingouin as pg
from scipy import stats

d = pd.read_csv({path})
"""
R_PACKAGES = "\n# Needs the R packages {names}; install them once with: {install}"
R_TABLE_ONE = """\
# Table 1: N in each dataset; n, M and SD (psych::describe) for numbers and scores, with
# Cronbach's alpha (psych::alpha) on pairwise complete cases; n (%) for answer options.
n_row <- function(dataset, present) {{
  data.frame(variable = "N", dataset = dataset, level = "", n = sum(present), mean = NA,
             sd = NA, percent = NA, alpha = NA)
}}
number_row <- function(variable, dataset, x, items = NULL) {{
  described <- psych::describe(x)
  alpha <- if (is.null(items)) NA else psych::alpha(items, warnings = FALSE)$total$raw_alpha
  data.frame(variable = variable, dataset = dataset, level = "", n = described$n,
             mean = described$mean, sd = described$sd, percent = NA, alpha = alpha)
}}
choice_rows <- function(variable, dataset, x, levels) {{
  counts <- table(factor(x, levels = levels, labels = names(levels)))
  data.frame(variable = variable, dataset = dataset, level = names(counts),
             n = as.vector(counts), mean = NA, sd = NA,
             percent = as.vector(100 * prop.table(counts)), alpha = NA)
}}
table1 <- rbind(
{rows}
)
rownames(table1) <- NULL
print(table1)
"""
PYTHON_TABLE_ONE = """\
# Table 1: N in each dataset; n, M and SD for numbers and scores, with Cronbach's alpha
# (pingouin) on pairwise complete cases; n (%) for answer options.
def n_row(dataset, present):
    return [dict(variable="N", dataset=dataset, level="", n=present.sum())]


def number_row(variable, dataset, x, items=None):
    alpha = np.nan if items is None else pg.cronbach_alpha(items, nan_policy="pairwise")[0]
    return [dict(variable=variable, dataset=dataset, level="", n=x.count(), mean=x.mean(),
                 sd=x.std(), alpha=alpha)]


def choice_rows(variable, dataset, x, levels):
    counts = x.map({{value: label for label, value in levels.items()}}).value_counts()
    counts = counts.reindex(list(levels), fill_value=0)
    return [dict(variable=variable, dataset=dataset, level=label, n=n,
                 percent=100 * n / counts.sum()) for label, n in counts.items()]


table1 = pd.DataFrame([
{rows}
], columns=["variable", "dataset", "level", "n", "mean", "sd", "percent", "alpha"])
print(table1)
"""
R_CORRELATIONS = """\
# Correlations: n, M and SD of each variable (psych::describe), then {coefficient} for each
# pair on everyone with both values (psych::corr.test, p values not adjusted).
variables <- c({columns})
descriptives <- data.frame(variable = variables,
                           psych::describe(d[variables])[c("n", "mean", "sd")], row.names = NULL)
print(descriptives)
test <- psych::corr.test(d[variables], method = "{method}", adjust = "none")
pairs <- which(lower.tri(test$r), arr.ind = TRUE)
correlations <- data.frame(x = variables[pairs[, "col"]], y = variables[pairs[, "row"]],
                           n = if (is.matrix(test$n)) test$n[pairs] else test$n,
                           r = test$r[pairs], p = test$p[pairs])
print(correlations)
"""
PYTHON_CORRELATIONS = """\
# Correlations: n, M and SD of each variable, then {coefficient} for each pair on everyone
# with both values (pingouin, p values not adjusted).
variables = [{columns}]
descriptives = pd.DataFrame(dict(variable=variables, n=d[variables].count().to_numpy(),
                                 mean=d[variables].mean().to_numpy(),
                                 sd=d[variables].std().to_numpy()))
print(descriptives)
correlations = pg.pairwise_corr(d, columns=variables, method="{method}", padjust="none")
correlations = correlations[["X", "Y", "n", "r", "p_unc"]]
correlations.columns = ["x", "y", "n", "r", "p"]
print(correlations)
"""
R_REGRESSION = """\
# Regression: {y_label} on each X by itself (lm), with r and its 95% CI (cor.test).
y <- {y}
regressions <- do.call(rbind, lapply(c({xs}), function(x) {{
  fit <- lm(d[[y]] ~ d[[x]])
  coefs <- summary(fit)$coefficients
  r <- cor.test(d[[x]], d[[y]])
  bounds <- if (is.null(r$conf.int)) c(NA, NA) else r$conf.int
  data.frame(x = x, n = nobs(fit), slope = coefs[2, 1], slope_se = coefs[2, 2],
             intercept = coefs[1, 1], intercept_se = coefs[1, 2], r = unname(r$estimate),
             r_low = bounds[1], r_high = bounds[2], r_squared = summary(fit)$r.squared,
             p = coefs[2, 4])
}}))
print(regressions)
"""
PYTHON_REGRESSION = """\
# Regression: {y_label} on each X by itself (pingouin), with r and its 95% CI (scipy, as
# pingouin rounds the interval).
y = {y}
rows = []
for x in [{xs}]:
    both = d[[x, y]].dropna()
    fit = pg.linear_regression(both[[x]], both[y])
    r = stats.pearsonr(both[x], both[y])
    low, high = r.confidence_interval()
    rows.append(dict(x=x, n=len(both), slope=fit["coef"][1], slope_se=fit["se"][1],
                     intercept=fit["coef"][0], intercept_se=fit["se"][0], r=r.statistic,
                     r_low=low, r_high=high,
                     r_squared=fit["r2"][0], p=fit["pval"][1]))
regressions = pd.DataFrame(rows)
print(regressions)
"""
R_GROUPS = """\
# Group comparison: {outcome_label} by {group_label}{left_out}
group <- factor(d[[{group}]], levels = c({values}), labels = c({labels}))
y <- d[[{outcome}]]
keep <- !is.na(group) & !is.na(y)
group <- group[keep]
y <- y[keep]
groups <- data.frame(group = levels(group), n = as.vector(table(group)),
                     mean = as.vector(tapply(y, group, mean)),
                     sd = as.vector(tapply(y, group, sd)))
print(groups)
"""
R_WELCH = """\
# Welch's t test (unequal variances); Cohen's d with the mean of the two group variances
# (effectsize).
test <- t.test(y ~ group)
print(test)
effect <- effectsize::cohens_d(y ~ group, pooled_sd = FALSE)
"""
R_STUDENT = """\
# Student's t test (equal variances); Cohen's d with the pooled SD (effectsize).
test <- t.test(y ~ group, var.equal = TRUE)
print(test)
effect <- effectsize::cohens_d(y ~ group, pooled_sd = TRUE)
"""
R_D_INTERVAL = """\
# The 95% CI of d as JASP gives it: the noncentral t at d's own noncentrality, with the
# test's df (MBESS::conf.limits.nct, which JASP uses).
n <- as.vector(table(group))
scale <- sqrt(prod(n) / sum(n))
limits <- MBESS::conf.limits.nct(ncp = effect$Cohens_d * scale, df = unname(test$parameter),
                                 conf.level = 0.95)
d_low <- limits$Lower.Limit / scale
d_high <- limits$Upper.Limit / scale
print(c(d = effect$Cohens_d, low = d_low, high = d_high))
"""
R_ANOVA = """\
# One-way analysis of variance; eta squared and omega squared with their 95% CIs (effectsize).
fit <- aov(y ~ group)
anova_table <- summary(fit)[[1]]
print(anova_table)
effect <- effectsize::eta_squared(fit, partial = FALSE, alternative = "two.sided")
print(effect)
omega <- effectsize::omega_squared(fit, partial = FALSE, alternative = "two.sided")
print(omega)
"""
PYTHON_GROUPS = """\
# Group comparison: {outcome_label} by {group_label}{left_out}
levels = [{labels}]
data = pd.DataFrame(dict(group=d[{group}].map({{{mapping}}}), y=d[{outcome}])).dropna()
groups = data.groupby("group")["y"].agg(["count", "mean", "std"]).reindex(levels)
groups = groups.reset_index().set_axis(["group", "n", "mean", "sd"], axis=1)
print(groups)
"""
PYTHON_WELCH = """\
# Welch's t test (unequal variances) and Cohen's d with the mean of the two group variances
# (pingouin). pingouin's own d uses the pooled SD, so d is written out here.
first, second = (data.loc[data["group"] == g, "y"] for g in levels)
test = pg.ttest(first, second, correction=True)
print(test)
# The difference's 95% CI from scipy, as pingouin rounds it.
low, high = stats.ttest_ind(first, second, equal_var=False).confidence_interval()
cohens_d = (first.mean() - second.mean()) / np.sqrt((first.var() + second.var()) / 2)
"""
PYTHON_STUDENT = """\
# Student's t test (equal variances) and Cohen's d with the pooled SD (pingouin).
first, second = (data.loc[data["group"] == g, "y"] for g in levels)
test = pg.ttest(first, second, correction=False)
print(test)
# The difference's 95% CI from scipy, as pingouin rounds it.
low, high = stats.ttest_ind(first, second, equal_var=True).confidence_interval()
cohens_d = pg.compute_effsize(first, second, eftype="cohen")
"""
PYTHON_D_INTERVAL = """\
# The 95% CI of d as JASP gives it: the noncentral t at d's own noncentrality, with the
# test's df, solved with scipy as MBESS::conf.limits.nct does in JASP.
from scipy import optimize

def limit(gap, step):
    # Step out from the observed noncentrality until the limit lies between two points.
    end = ncp + step
    while gap(end) > 0:
        end += step
    return optimize.brentq(gap, min(ncp, end), max(ncp, end), xtol=1e-12)


scale = np.sqrt(len(first) * len(second) / (len(first) + len(second)))
ncp, df = cohens_d * scale, test["dof"].iloc[0]
d_low = limit(lambda x: stats.nct.sf(ncp, df, x) - 0.025, -1) / scale
d_high = limit(lambda x: stats.nct.cdf(ncp, df, x) - 0.025, 1) / scale
print("Cohen's d:", cohens_d, "95% CI:", d_low, d_high)
"""
PYTHON_ANOVA = """\
# One-way analysis of variance and eta squared (pingouin, which has no omega squared).
test = pg.anova(data=data, dv="y", between="group", detailed=True, effsize="n2")
print(test)
"""
R_TEST_OUT = {
    TWO: "test_result <- data.frame(statistic = unname(test$statistic), "
    "df1 = unname(test$parameter), df2 = NA, p = test$p.value, low = test$conf.int[1], "
    "high = test$conf.int[2], effect = effect$Cohens_d, effect_low = d_low, "
    "effect_high = d_high, omega = NA, omega_low = NA, omega_high = NA)",
    "anova": 'test_result <- data.frame(statistic = anova_table[["F value"]][1], '
    'df1 = anova_table[["Df"]][1], df2 = anova_table[["Df"]][2], '
    'p = anova_table[["Pr(>F)"]][1], low = NA, high = NA, effect = effect$Eta2, '
    "effect_low = effect$CI_low, effect_high = effect$CI_high, omega = omega$Omega2, "
    "omega_low = omega$CI_low, omega_high = omega$CI_high)",
}
PYTHON_TEST_OUT = {
    TWO: "test_result = pd.DataFrame([dict(statistic=test['T'].iloc[0], "
    "df1=test['dof'].iloc[0], df2=np.nan, p=test['p_val'].iloc[0], "
    "low=low, high=high, effect=cohens_d, "
    "effect_low=d_low, effect_high=d_high, omega=np.nan, omega_low=np.nan, "
    "omega_high=np.nan)])",
    "anova": "test_result = pd.DataFrame([dict(statistic=test['F'][0], df1=test['DF'][0], "
    "df2=test['DF'][1], p=test['p_unc'][0], low=np.nan, high=np.nan, effect=test['n2'][0], "
    "effect_low=np.nan, effect_high=np.nan, omega=np.nan, omega_low=np.nan, "
    "omega_high=np.nan)])",
}


@dataclass
class Variable:
    key: str
    label: str
    dataset: str
    kind: str
    column: str
    options: list[tuple[float, str]] = field(default_factory=list)
    # Columns of the score's items, for alpha.
    items: list[str] = field(default_factory=list)


@dataclass
class Code:
    title: str
    r: str
    python: str
    # Results the GUI reads back; written only when the code runs here, never shown.
    outputs: tuple[str, ...] = ()
    r_footer: str = ""
    python_footer: str = ""
    packages: tuple[str, ...] = ()


@dataclass
class ComparisonPlan:
    kind: str
    code: Code
    left_out: list[tuple[str, int]]


@dataclass
class GroupStats:
    label: str
    n: int
    mean: float | None
    sd: float | None


@dataclass
class Comparison:
    test: str
    groups: list[GroupStats]
    statistic: float
    df1: float
    df2: float | None
    p: float
    effect: float
    low: float | None = None
    high: float | None = None
    effect_low: float | None = None
    effect_high: float | None = None
    omega: float | None = None
    omega_low: float | None = None
    omega_high: float | None = None
    left_out: list[tuple[str, int]] = field(default_factory=list)


class AnalysisData:
    # The columns one analysis reads, aligned to the people of the sample.
    def __init__(self, result: CatalogResult, sample: analysis.Sample) -> None:
        self.result = result
        self.sample = sample
        self.columns: dict[str, pd.Series] = {}

    def variable(self, key: str) -> Variable:
        return self.item(key) if key.startswith(ITEM_PREFIX) else self.score(key)

    def score(self, key: str, items: bool = False) -> Variable:
        score = next(s for s in self.result.catalog.scores if s.key == key)
        instrument = self.result.project.instruments[score.instrument_id]
        definition = next(s for s in instrument.scores if s.id == score.score_id)
        column = f"{score.score_id}_{score.dataset}"
        self.columns[column] = analysis.values(self.result, self.sample, key)
        names = []
        if items:
            found = score_items(self.result.datasets[score.dataset], score)
            names = [self.column_name(score.dataset, c) for c in found.columns]
            for name, source in zip(names, found.columns, strict=True):
                self.columns[name] = self.align(score.dataset, found[source].to_numpy(dtype=float))
        return Variable(
            key=key,
            label=f"{abbreviation(instrument)} {definition.label}",
            dataset=score.dataset,
            kind=SCORE,
            column=column,
            items=names if len(names) > 1 else [],
        )

    def item(self, key: str) -> Variable:
        variable = item_variable(self.result, key)
        options = [(float(o.value), o.label) for o in variable.response_options]
        column = self.column_name(variable.dataset, variable.column)
        self.columns[column] = analysis.values(self.result, self.sample, key)
        return Variable(
            key=key,
            label=item_label(self.result, variable),
            dataset=variable.dataset,
            kind=variable.type,
            column=column,
            options=options if variable.type == CHOICE else [],
        )

    def column_name(self, dataset: str, column: str) -> str:
        # A column name that two files share gets the dataset added, whatever is selected.
        shared = any(
            v.column == column and v.dataset != dataset for v in self.result.catalog.variables
        )
        return f"{column}_{dataset}" if shared else column

    def align(self, dataset: str, values: np.ndarray) -> pd.Series:
        return analysis.aligned(self.sample, dataset, values)

    def frame(self) -> pd.DataFrame:
        people, split = self.sample.people, self.sample.links.split
        keys = {link_name(self.result): [split.get(p, p) for p in people]}
        # A group taken person by person repeats, so its people get their own IDs.
        if split:
            keys[PERSON_ID] = [p if p in split else "" for p in people]
        presence = {
            f"in_{name}": [int(p in self.sample.links.rows[name]) for p in people]
            for name in self.sample.datasets
        }
        frame = pd.DataFrame({**keys, **presence}, index=people)
        return pd.concat([frame, pd.DataFrame(self.columns)], axis=1).reset_index(drop=True)


def abbreviation(instrument) -> str:
    return instrument.abbreviation or instrument.name


def link_name(result: CatalogResult) -> str:
    by = result.project.config.stats.correlate_by
    return "id" if by in ("id", "none") else by


def demographic_items(result: CatalogResult, datasets: list[str]) -> list[ResolvedVariable]:
    instruments = result.project.instruments
    return [
        v
        for name in datasets
        for v in result.catalog.variables_for(name)
        if instruments[v.instrument_id].kind == "demographics" and v.type in (CHOICE, NUMBER)
    ]


def other_numbers(result: CatalogResult, datasets: list[str]) -> list[ResolvedVariable]:
    instruments = result.project.instruments
    return [
        v
        for v in number_items(result, datasets)
        if instruments[v.instrument_id].kind != "demographics"
    ]


def item_label(result: CatalogResult, variable: ResolvedVariable) -> str:
    if variable.label:
        return variable.label
    instrument = result.project.instruments[variable.instrument_id]
    return f"{abbreviation(instrument)}: {next(iter(variable.text.values()))}"


def measures(result: CatalogResult, datasets: list[str]) -> dict[str, str]:
    # What Table 1 can show, across the chosen files: demographic items, scores, other numbers.
    found = {}
    for v in demographic_items(result, datasets):
        found[f"{ITEM_PREFIX}{v.instrument_id}.{v.item_id}"] = item_label(result, v)
    for name in datasets:
        for s in result.catalog.scores_for(name):
            instrument = result.project.instruments[s.instrument_id]
            found[f"{s.instrument_id}.{s.score_id}"] = f"{abbreviation(instrument)} {s.label}"
    for v in other_numbers(result, datasets):
        found[f"{ITEM_PREFIX}{v.instrument_id}.{v.item_id}"] = item_label(result, v)
    return found


def default_measures(result: CatalogResult, datasets: list[str]) -> list[str]:
    instruments = result.project.instruments

    def shown(key: str) -> bool:
        instrument = instruments[instrument_of(key)]
        if key.startswith(ITEM_PREFIX):
            return instrument.kind == "demographics"
        return is_total(instrument, key.split(".", 1)[1])

    return [key for key in measures(result, datasets) if shown(key)]


def measure_variables(
    data: AnalysisData, keys: list[str], items: bool = False
) -> list[tuple[str, list[Variable]]]:
    rows = []
    for key in keys:
        found = []
        for name in data.sample.datasets:
            if key.startswith(ITEM_PREFIX):
                full = f"{key}@{name}"
                if any(item_key(v) == full for v in data.result.catalog.variables_for(name)):
                    found.append(data.item(full))
            elif any(s.key == f"{key}@{name}" for s in data.result.catalog.scores_for(name)):
                found.append(data.score(f"{key}@{name}", items))
        if found:
            rows.append((found[0].label, found))
    return rows


def group_choices(
    result: CatalogResult, datasets: list[str], labels: dict[str, str]
) -> dict[str, str]:
    return {
        item_key(v): f"{item_label(result, v)} ({labels[v.dataset]})"
        for v in demographic_items(result, datasets)
        if v.type == CHOICE
    }


def r_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def headers(
    result: CatalogResult, sample: analysis.Sample, path: str, packages: tuple[str, ...]
) -> tuple[str, str]:
    matched = link_name(result)
    where = ", ".join(sample.datasets)
    title = f"Analysis of {result.project.config.project.name}, written by labcatalog."
    text = f"Sample: {len(sample.people)} people in {where}, matched by {matched}."
    if notes := analysis.group_notes(result, sample):
        text += "\n# " + notes
    needs = (
        R_PACKAGES.format(names=", ".join(packages), install=install_command(packages))
        if packages
        else ""
    )
    return (
        R_HEADER.format(title=title, sample=text, path=r_string(path), packages=needs),
        PYTHON_HEADER.format(title=title, sample=text, path=r_string(path)),
    )


def table_one_code(datasets: list[str], rows: list[tuple[str, list[Variable]]]) -> Code:
    r_rows = [f"  n_row({r_string(name)}, d[[{r_string(f'in_{name}')}]])" for name in datasets]
    py_rows = [f"    *n_row({r_string(name)}, d[{r_string(f'in_{name}')}])," for name in datasets]
    for label, variables in rows:
        for v in variables:
            args = f"{r_string(label)}, {r_string(v.dataset)}, d[[{r_string(v.column)}]]"
            py_args = f"{r_string(label)}, {r_string(v.dataset)}, d[{r_string(v.column)}]"
            if v.kind == CHOICE:
                levels = ", ".join(
                    f"{r_string(text)} = {number(value)}" for value, text in v.options
                )
                py_levels = ", ".join(
                    f"{r_string(text)}: {number(value)}" for value, text in v.options
                )
                r_rows.append(f"  choice_rows({args}, c({levels}))")
                py_rows.append(f"    *choice_rows({py_args}, {{{py_levels}}}),")
            elif v.items:
                items = ", ".join(r_string(c) for c in v.items)
                r_rows.append(f"  number_row({args}, d[c({items})])")
                py_rows.append(f"    *number_row({py_args}, d[[{items}]]),")
            else:
                r_rows.append(f"  number_row({args})")
                py_rows.append(f"    *number_row({py_args}),")
    return Code(
        title="Table 1",
        r=R_TABLE_ONE.format(rows=",\n".join(r_rows)),
        python=PYTHON_TABLE_ONE.format(rows="\n".join(py_rows)),
        outputs=("table1",),
        packages=("psych",),
    )


def correlation_code(variables: list[Variable], method: str = "pearson") -> Code:
    columns = ", ".join(r_string(v.column) for v in variables)
    coefficient = "Spearman's rho" if method == "spearman" else "Pearson r"
    fields = dict(columns=columns, method=method, coefficient=coefficient)
    return Code(
        title="Correlations",
        r=R_CORRELATIONS.format(**fields),
        python=PYTHON_CORRELATIONS.format(**fields),
        outputs=("descriptives", "correlations"),
        packages=("psych",),
    )


def regression_code(xs: list[Variable], y: Variable) -> Code:
    xs_text = ", ".join(r_string(v.column) for v in xs)
    fields = dict(y=r_string(y.column), xs=xs_text, y_label=y.label)
    return Code(
        title="Regression",
        r=R_REGRESSION.format(**fields),
        python=PYTHON_REGRESSION.format(**fields),
        outputs=("regressions",),
    )


def fittable(frame: pd.DataFrame, x: str, y: str) -> bool:
    # A line needs three people with both values, and both must vary.
    both = frame[[x, y]].dropna()
    return (
        len(both) >= defaults.MIN_CORRELATION_N and both[x].nunique() > 1 and both[y].nunique() > 1
    )


def group_sizes(
    frame: pd.DataFrame, group: Variable, outcome: Variable
) -> list[tuple[float, str, int]]:
    both = frame[[group.column, outcome.column]].dropna()
    return [
        (value, text, int((both[group.column] == value).sum())) for value, text in group.options
    ]


def comparison_plan(
    frame: pd.DataFrame, group: Variable, outcome: Variable, t_test: str = WELCH
) -> ComparisonPlan | None:
    sizes = group_sizes(frame, group, outcome)
    kept = [(value, text) for value, text, n in sizes if n >= MIN_GROUP]
    if len(kept) < 2:
        return None
    left = [(text, n) for _, text, n in sizes if n < MIN_GROUP]
    shown = ", ".join(f"{text} ({n})" for text, n in left)
    left_out = f"\n# Left out, fewer than {MIN_GROUP} people: {shown}." if left else ""
    kind = t_test if len(kept) == 2 else ANOVA
    labels = ", ".join(r_string(text) for _, text in kept)
    fields = dict(
        group=r_string(group.column),
        outcome=r_string(outcome.column),
        group_label=group.label,
        outcome_label=outcome.label,
        left_out=left_out,
        labels=labels,
    )
    r = R_GROUPS.format(values=", ".join(number(v) for v, _ in kept), **fields)
    python = PYTHON_GROUPS.format(
        mapping=", ".join(f"{number(v)}: {r_string(t)}" for v, t in kept), **fields
    )
    tests = {
        WELCH: (R_WELCH + R_D_INTERVAL, PYTHON_WELCH + PYTHON_D_INTERVAL),
        STUDENT: (R_STUDENT + R_D_INTERVAL, PYTHON_STUDENT + PYTHON_D_INTERVAL),
        ANOVA: (R_ANOVA, PYTHON_ANOVA),
    }
    out = ANOVA if kind == ANOVA else TWO
    code = Code(
        title="Group comparison",
        r=r + tests[kind][0],
        python=python + tests[kind][1],
        outputs=("groups", "test_result"),
        r_footer=R_TEST_OUT[out],
        python_footer=PYTHON_TEST_OUT[out],
        packages=("effectsize",) if kind == ANOVA else ("effectsize", "MBESS"),
    )
    return ComparisonPlan(kind, code, left)


def page_script(
    result: CatalogResult,
    sample: analysis.Sample,
    scores: list[str],
    xs: list[str],
    y: str | None,
    group: str | None,
    outcome: str | None,
) -> tuple[str, str, pd.DataFrame] | None:
    # Each part of the Analysis page that has enough chosen to run, in page order.
    data = AnalysisData(result, sample)
    codes = []
    if len(scores) >= 2:
        method = result.project.config.stats.correlation
        codes.append(correlation_code([data.variable(k) for k in scores], method))
    if y is not None:
        target = data.variable(y)
        variables = [data.variable(x) for x in xs if x != y]
        frame = data.frame()
        fitted = [v for v in variables if fittable(frame, v.column, target.column)]
        if fitted:
            codes.append(regression_code(fitted, target))
    if group is not None and outcome is not None:
        # The frame holds only the variables asked for so far, so ask first.
        grouping, measured = data.item(group), data.variable(outcome)
        t_test = result.project.config.stats.t_test
        plan = comparison_plan(data.frame(), grouping, measured, t_test)
        if plan is not None:
            codes.append(plan.code)
    if not codes:
        return None
    r_text, python_text = script(result, sample, codes)
    return r_text, python_text, data.frame()


def script(result: CatalogResult, sample: analysis.Sample, codes: list[Code]) -> tuple[str, str]:
    packages = tuple(dict.fromkeys(p for c in codes for p in c.packages))
    r_head, py_head = headers(result, sample, DATA_FILE, packages)
    return (
        "\n".join([r_head, *[c.r for c in codes]]),
        "\n".join([py_head, *[c.python for c in codes]]),
    )


def run_code(
    result: CatalogResult,
    sample: analysis.Sample,
    frame: pd.DataFrame,
    code: Code,
    rscript: str | None,
) -> tuple[dict[str, pd.DataFrame], str]:
    # R when the Settings page names an Rscript, otherwise the Python version, run here.
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        frame.to_csv(folder / DATA_FILE, index=False)
        r_head, py_head = headers(result, sample, (folder / DATA_FILE).as_posix(), code.packages)
        if rscript:
            writes = [
                f"write.csv({name}, {r_string((folder / f'{name}.csv').as_posix())}, row.names = FALSE)"
                for name in code.outputs
            ]
            path = folder / "analysis.R"
            prelude = package_check(code.packages) if code.packages else ""
            path.write_text(
                "\n".join([prelude, r_head, code.r, code.r_footer, *writes]), encoding="utf-8"
            )
            run_r(rscript, [str(path)])
            return {n: pd.read_csv(folder / f"{n}.csv") for n in code.outputs}, R
        names: dict = {}
        with contextlib.redirect_stdout(io.StringIO()):
            exec("\n".join([py_head, code.python, code.python_footer]), names)
        return {n: names[n] for n in code.outputs}, PYTHON


def read_comparison(found: dict[str, pd.DataFrame], plan: ComparisonPlan) -> Comparison:
    groups = [
        GroupStats(str(row.group), int(row.n), none(row.mean), none(row.sd))
        for row in found["groups"].itertuples()
    ]
    test = found["test_result"].iloc[0]
    return Comparison(
        test=plan.kind,
        groups=groups,
        statistic=float(test["statistic"]),
        df1=float(test["df1"]),
        df2=none(test["df2"]),
        p=float(test["p"]),
        effect=float(test["effect"]),
        low=none(test["low"]),
        high=none(test["high"]),
        effect_low=none(test["effect_low"]),
        effect_high=none(test["effect_high"]),
        omega=none(test["omega"]),
        omega_low=none(test["omega_low"]),
        omega_high=none(test["omega_high"]),
        left_out=plan.left_out,
    )


def none(value) -> float | None:
    return None if pd.isna(value) else float(value)


def read_correlations(
    found: dict[str, pd.DataFrame], columns: list[str]
) -> tuple[list[tuple[int, float | None, float | None]], list[list[analysis.Correlation]]]:
    described = [
        (int(row.n), none(row.mean), none(row.sd)) for row in found["descriptives"].itertuples()
    ]
    pairs = {}
    for row in found["correlations"].itertuples():
        found_pair = analysis.Correlation(int(row.n), none(row.r), none(row.p))
        pairs[(row.x, row.y)] = pairs[(row.y, row.x)] = found_pair
    matrix = [
        [analysis.Correlation(described[i][0]) if a == b else pairs[(a, b)] for b in columns]
        for i, a in enumerate(columns)
    ]
    return described, matrix


def read_regressions(
    found: dict[str, pd.DataFrame], keys: dict[str, str]
) -> dict[str, analysis.Fit]:
    # keys maps each X column in the data back to its score key.
    return {
        keys[row.x]: analysis.Fit(
            analysis.Correlation(
                int(row.n), none(row.r), none(row.p), none(row.r_low), none(row.r_high)
            ),
            float(row.slope),
            float(row.slope_se),
            float(row.intercept),
            float(row.intercept_se),
        )
        for row in found["regressions"].itertuples()
    }
