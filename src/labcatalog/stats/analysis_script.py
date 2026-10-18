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
    STUDY_KEY,
    first_key,
    instrument_of,
    item_key,
    item_variable,
    number_items,
    parts,
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
# Needs pandas, scipy and statsmodels (pip install statsmodels).
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
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
# on pairwise complete cases; n (%) for answer options.
def cronbach_alpha(items):
    # From the pairwise covariances, as JASP computes it.
    cov = items.cov().to_numpy()
    k = len(cov)
    return k / (k - 1) * (1 - np.trace(cov) / cov.sum())


def n_row(dataset, present):
    return [dict(variable="N", dataset=dataset, level="", n=present.sum())]


def number_row(variable, dataset, x, items=None):
    alpha = np.nan if items is None else cronbach_alpha(items)
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
# pair on everyone with both values (cor.test, p values not adjusted; Spearman's p is exact
# when there are no ties).
variables <- c({columns})
descriptives <- data.frame(variable = variables,
                           psych::describe(d[variables])[c("n", "mean", "sd")], row.names = NULL)
print(descriptives)
pairs <- t(combn(variables, 2))
correlations <- do.call(rbind, lapply(seq_len(nrow(pairs)), function(i) {{
  x <- pairs[i, 1]
  y <- pairs[i, 2]
  n <- sum(complete.cases(d[[x]], d[[y]]))
  test <- if (n > 2) suppressWarnings(cor.test(d[[x]], d[[y]], method = "{method}"))
  data.frame(x = x, y = y, n = n, r = if (is.null(test)) NA else unname(test$estimate),
             p = if (is.null(test)) NA else test$p.value)
}}))
print(correlations)
"""
PYTHON_CORRELATIONS = """\
# Correlations: n, M and SD of each variable, then {coefficient} for each pair on everyone
# with both values (scipy, p values not adjusted; Spearman's p uses the t approximation).
variables = [{columns}]
descriptives = pd.DataFrame(dict(variable=variables, n=d[variables].count().to_numpy(),
                                 mean=d[variables].mean().to_numpy(),
                                 sd=d[variables].std().to_numpy()))
print(descriptives)
rows = []
for i, x in enumerate(variables):
    for y in variables[i + 1:]:
        both = d[[x, y]].dropna()
        test = stats.{function}(both[x], both[y]) if len(both) > 2 else None
        rows.append(dict(x=x, y=y, n=len(both), r=np.nan if test is None else test.statistic,
                         p=np.nan if test is None else test.pvalue))
correlations = pd.DataFrame(rows, columns=["x", "y", "n", "r", "p"])
print(correlations)
"""
R_STUDY_CORRELATIONS = """\
# Correlations pooled over studies: n, M and SD of each variable (psych::describe), then
# {coefficient} for each pair within studies, on everyone with both values: the correlation of
# what is left of each variable once the study means are taken out (lm on the study), and the
# p value of the variable's coefficient in lm with the study (p values not adjusted).{ranks}
variables <- c({columns})
descriptives <- data.frame(variable = variables,
                           psych::describe(d[variables])[c("n", "mean", "sd")], row.names = NULL)
print(descriptives)
study <- factor(d$study)
within_study <- function(v, s) if (nlevels(s) > 1) resid(lm(v ~ s)) else v - mean(v)
pairs <- t(combn(variables, 2))
correlations <- do.call(rbind, lapply(seq_len(nrow(pairs)), function(i) {{
  x <- pairs[i, 1]
  y <- pairs[i, 2]
  keep <- complete.cases(d[[x]], d[[y]])
  n <- sum(keep)
  s <- droplevels(study[keep])
  xs <- {transform}(d[[x]][keep])
  ys <- {transform}(d[[y]][keep])
  ok <- n > nlevels(s) + 1 && sd(xs) > 0 && sd(ys) > 0
  fit <- if (!ok) NULL else if (nlevels(s) > 1) lm(ys ~ xs + s) else lm(ys ~ xs)
  coefs <- if (is.null(fit)) NULL else summary(fit)$coefficients
  found <- !is.null(coefs) && "xs" %in% rownames(coefs)
  data.frame(x = x, y = y, n = n,
             r = if (found) cor(within_study(xs, s), within_study(ys, s)) else NA,
             p = if (found) coefs["xs", 4] else NA)
}}))
print(correlations)
"""
PYTHON_STUDY_CORRELATIONS = """\
# Correlations pooled over studies: n, M and SD of each variable, then {coefficient} for each
# pair within studies, on everyone with both values: the correlation of what is left of each
# variable once the study means are taken out (statsmodels OLS on the study), and the p value
# of the variable's coefficient in OLS with the study (p values not adjusted).{ranks}
variables = [{columns}]
descriptives = pd.DataFrame(dict(variable=variables, n=d[variables].count().to_numpy(),
                                 mean=d[variables].mean().to_numpy(),
                                 sd=d[variables].std().to_numpy()))
print(descriptives)


def within_study(v, dummies):
    if dummies.shape[1] == 0:
        return v - v.mean()
    return sm.OLS(v, sm.add_constant(dummies)).fit().resid


rows = []
for i, x in enumerate(variables):
    for y in variables[i + 1:]:
        both = d[[x, y, "study"]].dropna()
        dummies = pd.get_dummies(both["study"].astype(int).astype(str), drop_first=True,
                                 dtype=float)
        xs, ys = both[x]{rank}.rename("xs"), both[y]{rank}
        r = p = np.nan
        if len(both) > dummies.shape[1] + 2 and xs.std() > 0 and ys.std() > 0:
            fit = sm.OLS(ys, sm.add_constant(pd.concat([xs, dummies], axis=1))).fit()
            r = np.corrcoef(within_study(xs, dummies), within_study(ys, dummies))[0, 1]
            p = fit.pvalues["xs"]
        rows.append(dict(x=x, y=y, n=len(both), r=r, p=p))
correlations = pd.DataFrame(rows, columns=["x", "y", "n", "r", "p"])
print(correlations)
"""
R_MISSING = """# Missing data: how many people have and lack each variable, then each pattern of what people
# have (1) and lack (0), the most common first.
variables <- c({columns})
present <- as.data.frame(lapply(d[variables], function(x) as.integer(!is.na(x))),
                         check.names = FALSE)
missing_counts <- data.frame(variable = variables, n = colSums(present),
                             missing = colSums(1L - present), row.names = NULL)
print(missing_counts)
key <- do.call(paste0, present)
counts <- table(key)
missing_patterns <- present[match(names(counts), key), , drop = FALSE]
missing_patterns$people <- as.integer(counts)
missing_patterns <- missing_patterns[order(-missing_patterns$people, names(counts)), , drop = FALSE]
rownames(missing_patterns) <- NULL
print(missing_patterns)
"""
PYTHON_MISSING = """# Missing data: how many people have and lack each variable, then each pattern of what people
# have (1) and lack (0), the most common first.
variables = [{columns}]
present = d[variables].notna().astype(int)
missing_counts = pd.DataFrame(dict(variable=variables, n=present.sum().to_numpy(),
                                   missing=(1 - present).sum().to_numpy()))
print(missing_counts)
key = present.astype(str).agg("".join, axis=1)
missing_patterns = present.groupby(key).first()
missing_patterns["people"] = key.value_counts()
missing_patterns = missing_patterns.rename_axis("key").reset_index().sort_values(
    ["people", "key"], ascending=[False, True]).drop(columns="key").reset_index(drop=True)
print(missing_patterns)
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
# Regression: {y_label} on each X by itself (statsmodels), with r and its 95% CI (scipy).
y = {y}
rows = []
for x in [{xs}]:
    both = d[[x, y]].dropna()
    fit = sm.OLS(both[y], sm.add_constant(both[[x]])).fit()
    r = stats.pearsonr(both[x], both[y])
    low, high = r.confidence_interval()
    rows.append(dict(x=x, n=len(both), slope=fit.params[x], slope_se=fit.bse[x],
                     intercept=fit.params["const"], intercept_se=fit.bse["const"],
                     r=r.statistic, r_low=low, r_high=high, r_squared=fit.rsquared,
                     p=fit.pvalues[x]))
regressions = pd.DataFrame(rows)
print(regressions)
"""
R_STUDY_REGRESSION = """\
# Regression pooled over studies: {y_label} on each X by itself with the study as a fixed
# effect (lm with the study as a factor); the intercept is the first study's, and r is the
# correlation within studies, of what is left of X and Y once the study means are taken out.
y <- {y}
study <- factor(d$study)
regressions <- do.call(rbind, lapply(c({xs}), function(x) {{
  keep <- complete.cases(d[[x]], d[[y]])
  s <- droplevels(study[keep])
  xs <- d[[x]][keep]
  ys <- d[[y]][keep]
  within_study <- function(v) if (nlevels(s) > 1) resid(lm(v ~ s)) else v - mean(v)
  fit <- if (nlevels(s) > 1) lm(ys ~ xs + s) else lm(ys ~ xs)
  coefs <- summary(fit)$coefficients
  data.frame(x = x, n = nobs(fit), slope = coefs["xs", 1], slope_se = coefs["xs", 2],
             intercept = coefs[1, 1], intercept_se = coefs[1, 2],
             r = cor(within_study(xs), within_study(ys)), r_low = NA, r_high = NA,
             r_squared = summary(fit)$r.squared, p = coefs["xs", 4])
}}))
print(regressions)
"""
PYTHON_STUDY_REGRESSION = """\
# Regression pooled over studies: {y_label} on each X by itself with the study as a fixed
# effect (statsmodels OLS with a dummy for each study but the first); the intercept is the
# first study's, and r is the correlation within studies, of what is left of X and Y once the
# study means are taken out.
y = {y}
rows = []
for x in [{xs}]:
    both = d[[x, y, "study"]].dropna()
    dummies = pd.get_dummies(both["study"].astype(int).astype(str), drop_first=True, dtype=float)
    fit = sm.OLS(both[y], sm.add_constant(pd.concat([both[x], dummies], axis=1))).fit()
    if dummies.shape[1]:
        rest = [sm.OLS(both[v], sm.add_constant(dummies)).fit().resid for v in (x, y)]
    else:
        rest = [both[v] - both[v].mean() for v in (x, y)]
    rows.append(dict(x=x, n=len(both), slope=fit.params[x], slope_se=fit.bse[x],
                     intercept=fit.params["const"], intercept_se=fit.bse["const"],
                     r=np.corrcoef(rest[0], rest[1])[0, 1], r_low=np.nan, r_high=np.nan,
                     r_squared=fit.rsquared, p=fit.pvalues[x]))
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
# Welch's t test (unequal variances, scipy) and Cohen's d with the mean of the two group
# variances, as JASP gives it with Welch's test.
first, second = (data.loc[data["group"] == g, "y"] for g in levels)
test = stats.ttest_ind(first, second, equal_var=False)
print(test)
low, high = test.confidence_interval()
cohens_d = (first.mean() - second.mean()) / np.sqrt((first.var() + second.var()) / 2)
"""
PYTHON_STUDENT = """\
# Student's t test (equal variances, scipy) and Cohen's d with the pooled SD.
first, second = (data.loc[data["group"] == g, "y"] for g in levels)
test = stats.ttest_ind(first, second, equal_var=True)
print(test)
low, high = test.confidence_interval()
pooled = np.sqrt(((len(first) - 1) * first.var() + (len(second) - 1) * second.var())
                 / (len(first) + len(second) - 2))
cohens_d = (first.mean() - second.mean()) / pooled
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
ncp, df = cohens_d * scale, test.df
d_low = limit(lambda x: stats.nct.sf(ncp, df, x) - 0.025, -1) / scale
d_high = limit(lambda x: stats.nct.cdf(ncp, df, x) - 0.025, 1) / scale
print("Cohen's d:", cohens_d, "95% CI:", d_low, d_high)
"""
PYTHON_ANOVA = """\
# One-way analysis of variance (statsmodels) and eta squared, the groups' share of the sums
# of squares; omega squared is computed only in R.
test = sm.stats.anova_lm(smf.ols("y ~ C(group)", data=data).fit(), typ=2)
print(test)
eta_squared = test["sum_sq"].iloc[0] / test["sum_sq"].sum()
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
    TWO: "test_result = pd.DataFrame([dict(statistic=test.statistic, "
    "df1=test.df, df2=np.nan, p=test.pvalue, "
    "low=low, high=high, effect=cohens_d, "
    "effect_low=d_low, effect_high=d_high, omega=np.nan, omega_low=np.nan, "
    "omega_high=np.nan)])",
    "anova": "test_result = pd.DataFrame([dict(statistic=test['F'].iloc[0], "
    "df1=test['df'].iloc[0], df2=test['df'].iloc[1], p=test['PR(>F)'].iloc[0], "
    "low=np.nan, high=np.nan, effect=eta_squared, "
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
        item = key.startswith(ITEM_PREFIX) or key == STUDY_KEY
        return self.item(key) if item else self.score(key)

    def score(self, key: str, items: bool = False) -> Variable:
        score = next(s for s in self.result.catalog.scores if s.key == first_key(key))
        instrument = self.result.project.instruments[score.instrument_id]
        definition = next(s for s in instrument.scores if s.id == score.score_id)
        column = f"{score.score_id}_{'_'.join(parts(key))}"
        self.columns[column] = analysis.values(self.result, self.sample, key)
        names = []
        # A pooled score's items differ from file to file, so it has none.
        if items and len(parts(key)) == 1:
            found = score_items(self.result.datasets[score.dataset], score)
            names = [self.column_name(score.dataset, c) for c in found.columns]
            for name, source in zip(names, found.columns, strict=True):
                self.columns[name] = self.align(score.dataset, found[source].to_numpy(dtype=float))
        return Variable(
            key=key,
            label=f"{abbreviation(instrument)} {definition.label}",
            dataset=key.rsplit("@", 1)[1],
            kind=SCORE,
            column=column,
            items=names if len(names) > 1 else [],
        )

    def item(self, key: str) -> Variable:
        if key == STUDY_KEY:
            options = analysis.study_options(self.result, self.sample)
            return Variable(STUDY_KEY, "Study", "", CHOICE, STUDY_KEY, options)
        variable = item_variable(self.result, key)
        options = [(float(o.value), o.label) for o in variable.response_options]
        names = parts(key)
        column = (
            self.column_name(variable.dataset, variable.column)
            if len(names) == 1
            else f"{variable.column}_{'_'.join(names)}"
        )
        self.columns[column] = analysis.values(self.result, self.sample, key)
        return Variable(
            key=key,
            label=item_label(self.result, variable),
            dataset=key.rsplit("@", 1)[1],
            kind=variable.type,
            column=column,
            options=options if variable.type == CHOICE else [],
        )

    def column_name(self, dataset: str, column: str) -> str:
        # A column name that two files share gets the dataset added, whatever is selected.
        catalog = self.result.catalog
        shared = any(v.column == column and v.dataset != dataset for v in catalog.variables) or any(
            v.column == column for v in catalog.roster_variables
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
        if analysis.pooling(self.result, self.sample.datasets):
            keys[STUDY_KEY] = analysis.study_numbers(self.result, self.sample).to_list()
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
        for v in analysis.items_for(result, name)
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
                if any(item_key(v) == full for v in analysis.items_for(data.result, name)):
                    found.append(data.item(full))
            elif any(s.key == f"{key}@{name}" for s in data.result.catalog.scores_for(name)):
                found.append(data.score(f"{key}@{name}", items))
        if found:
            rows.append((found[0].label, found))
    return rows


def group_choices(
    result: CatalogResult, datasets: list[str], labels: dict[str, str]
) -> dict[str, str]:
    found = {
        item_key(v): f"{item_label(result, v)} ({labels[v.dataset]})"
        for v in demographic_items(result, datasets)
        if v.type == CHOICE
    }
    if not analysis.pooling(result, datasets):
        return found
    return {STUDY_KEY: "Study", **analysis.pooled(result, datasets, found)}


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


def missing_code(variables: list[Variable]) -> Code:
    columns = ", ".join(r_string(v.column) for v in variables)
    return Code(
        title="Missing data",
        r=R_MISSING.format(columns=columns),
        python=PYTHON_MISSING.format(columns=columns),
        outputs=("missing_counts", "missing_patterns"),
    )


@dataclass
class MissingData:
    # Per variable: its column, people with a value and people without.
    counts: list[tuple[str, int, int]]
    # Each pattern of which variables people have, and how many people have it.
    patterns: list[tuple[tuple[bool, ...], int]]

    @property
    def people(self) -> int:
        return sum(n for _, n in self.patterns)

    @property
    def complete(self) -> int:
        return sum(n for present, n in self.patterns if all(present))


def read_missing(found: dict[str, pd.DataFrame], columns: list[str]) -> MissingData:
    counts = [
        (str(r.variable), int(r.n), int(r.missing)) for r in found["missing_counts"].itertuples()
    ]
    frame = found["missing_patterns"]
    patterns = [
        (tuple(bool(row[c]) for c in columns), int(row["people"])) for _, row in frame.iterrows()
    ]
    return MissingData(counts, patterns)


def correlation_code(
    variables: list[Variable], method: str = "pearson", by_study: bool = False
) -> Code:
    columns = ", ".join(r_string(v.column) for v in variables)
    spearman = method == "spearman"
    fields = dict(
        columns=columns,
        method=method,
        coefficient="Spearman's rho" if spearman else "Pearson r",
        function="spearmanr" if spearman else "pearsonr",
        # Spearman's within studies is Pearson's on the ranks of each pair.
        ranks="\n# Spearman's rho: the same on the ranks of each pair." if spearman else "",
        transform="rank" if spearman else "as.numeric",
        rank=".rank()" if spearman else "",
    )
    r, python = (
        (R_STUDY_CORRELATIONS, PYTHON_STUDY_CORRELATIONS)
        if by_study
        else (R_CORRELATIONS, PYTHON_CORRELATIONS)
    )
    return Code(
        title="Correlations",
        r=r.format(**fields),
        python=python.format(**fields),
        outputs=("descriptives", "correlations"),
        packages=("psych",),
    )


def regression_code(xs: list[Variable], y: Variable, by_study: bool = False) -> Code:
    xs_text = ", ".join(r_string(v.column) for v in xs)
    fields = dict(y=r_string(y.column), xs=xs_text, y_label=y.label)
    r, python = (
        (R_STUDY_REGRESSION, PYTHON_STUDY_REGRESSION)
        if by_study
        else (R_REGRESSION, PYTHON_REGRESSION)
    )
    return Code(
        title="Regression",
        r=r.format(**fields),
        python=python.format(**fields),
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
