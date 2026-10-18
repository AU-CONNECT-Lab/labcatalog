import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog.stats import analysis_script
from labcatalog.stats.analysis_script import (
    ANOVA,
    CHOICE,
    MIN_GROUP,
    STUDENT,
    AnalysisData,
    Code,
    ComparisonPlan,
    Variable,
    number,
    r_string,
)
from labcatalog.stats.rbridge import IMPUTATION_PACKAGES as PACKAGES

AVAILABLE = "available"
IMPUTE = "impute"
METHODS = {AVAILABLE: "Available cases", IMPUTE: "Multiple imputation"}
CACHE_FOLDER = "labcatalog_imputations"
# quickpred keeps the predictors that correlate at least this much with a column or its missingness.
MIN_CORRELATION = 0.1

R_IMPUTE = """\
# Multiple imputation with mice: {m} imputed data sets by predictive mean matching (answer
# options of demographics as categories), seed {seed}. Imputed: {what}.
# Each column is predicted by those that correlate at least {mincor} with it or with its
# missingness (quickpred). The imputation is kept in the file below, named after the data and
# these choices, and every analysis reads it again; delete the file to impute again.
imputation_file <- {file}
imputed_columns <- c({columns})
factor_columns <- c({factors})
if (!file.exists(imputation_file)) {{
  source <- d[imputed_columns]
  source[factor_columns] <- lapply(source[factor_columns], factor)
  predictors <- mice::quickpred(source, mincor = {mincor})
  imputation <- mice::mice(source, m = {m}, seed = {seed}, predictorMatrix = predictors,
                           printFlag = FALSE)
  saveRDS(imputation, imputation_file)
}}
imputation <- readRDS(imputation_file)
# Each imputed data set, with every score computed again from its imputed items.
completed <- lapply(seq_len({m}), function(i) {{
  x <- d
  x[imputed_columns] <- mice::complete(imputation, i)
  x[factor_columns] <- lapply(x[factor_columns], function(v) as.numeric(as.character(v)))
{scores}  x
}})
"""
PYTHON_IMPUTE = """\
# Multiple imputation runs in R (mice); this script gives the same analysis on everyone with
# values instead.
"""


@dataclass
class ImputationPlan:
    m: int
    seed: int
    # Item columns imputed and scored again, numbers and categories imputed as they are, helpers.
    items: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    factors: list[str] = field(default_factory=list)
    auxiliaries: list[str] = field(default_factory=list)
    # Each score column, sum or mean, and its item columns.
    scores: list[tuple[str, str, list[str]]] = field(default_factory=list)

    @property
    def columns(self) -> list[str]:
        return list(dict.fromkeys([*self.items, *self.numbers, *self.factors, *self.auxiliaries]))


def plan(
    data: AnalysisData, keys: list[str], auxiliaries: list[str], m: int, seed: int
) -> ImputationPlan:
    found = ImputationPlan(m, seed)
    scores = {s.key: s for s in data.result.catalog.scores}
    for key in keys:
        if key not in scores:
            v = data.variable(key)
            (found.factors if v.kind == CHOICE else found.numbers).append(v.column)
            continue
        v = data.score(key, items=True)
        if v.items:
            found.items += [c for c in v.items if c not in found.items]
            found.scores.append((v.column, scores[key].method, v.items))
        else:
            found.numbers.append(v.column)
    found.auxiliaries = [data.score(k).column for k in auxiliaries if k not in keys]
    return found


def file_name(frame: pd.DataFrame, found: ImputationPlan) -> str:
    # The same data and choices give the same imputation, so it is named after their digest.
    spec = f"{found.m} {found.seed} {MIN_CORRELATION} {found.columns} {found.factors}\n"
    data = frame[found.columns].to_csv(index=False)
    digest = hashlib.sha256((spec + data).encode("utf-8")).hexdigest()[:16]
    return f"imputation_{digest}.rds"


def cache_path(frame: pd.DataFrame, found: ImputationPlan) -> Path:
    folder = Path(tempfile.gettempdir()) / CACHE_FOLDER
    folder.mkdir(exist_ok=True)
    return folder / file_name(frame, found)


def impute_r(found: ImputationPlan, file: str) -> str:
    parts = ["the items of the chosen scores"] if found.items else []
    if found.numbers:
        parts.append("the chosen numbers")
    if found.factors:
        parts.append("the chosen answer options")
    if found.auxiliaries:
        n = len(found.auxiliaries)
        parts.append(
            f"{n} other score{'s' if n > 1 else ''} that help{'' if n > 1 else 's'} impute them"
        )
    function = {"sum": "rowSums", "mean": "rowMeans"}
    lines = "".join(
        f"  x[[{r_string(column)}]] <- {function[method]}(x[c({quoted(items)})])\n"
        for column, method, items in found.scores
    )
    return R_IMPUTE.format(
        seed=found.seed,
        m=found.m,
        what="; ".join(parts),
        mincor=MIN_CORRELATION,
        columns=quoted(found.columns),
        factors=quoted(found.factors),
        scores=lines,
        file=r_string(file),
    )


def quoted(columns: list[str]) -> str:
    return ", ".join(r_string(c) for c in columns)


R_SUMMARY = """\
# The imputed values beside the observed ones, over all imputed data sets, and what mice
# reported doing, such as leaving out a column that another one predicts exactly.
imputed_summary <- do.call(rbind, lapply(imputed_columns, function(column) {{
  seen <- d[[column]]
  drawn <- as.numeric(unlist(lapply(imputation$imp[[column]], as.character)))
  data.frame(variable = column, missing = sum(is.na(seen)),
             observed_mean = mean(seen, na.rm = TRUE), observed_sd = sd(seen, na.rm = TRUE),
             imputed_mean = if (length(drawn)) mean(drawn) else NA,
             imputed_sd = if (length(drawn) > 1) sd(drawn) else NA)
}}))
print(imputed_summary)
logged <- imputation$loggedEvents
imputation_events <- if (is.null(logged)) {{
  data.frame(it = integer(), im = integer(), dep = character(), meth = character(),
             out = character())
}} else logged
print(imputation_events)
# Every imputed data set stacked under the observed data: .imp 0 is the data as observed.
imputed_long <- do.call(rbind, c(list(cbind(.imp = 0L, d)),
                                 lapply(seq_along(completed),
                                        function(i) cbind(.imp = i, completed[[i]]))))
"""


@dataclass
class ImputedColumn:
    column: str
    missing: int
    observed_mean: float | None
    observed_sd: float | None
    imputed_mean: float | None
    imputed_sd: float | None


def summary_code(found: ImputationPlan, file: str) -> Code:
    return Code(
        title="Multiple imputation",
        r=impute_r(found, file) + R_SUMMARY.format(),
        python=PYTHON_IMPUTE,
        outputs=("imputed_summary", "imputation_events", "imputed_long"),
        packages=PACKAGES,
    )


def read_summary(found: dict) -> tuple[list[ImputedColumn], list[str]]:
    none = analysis_script.none
    columns = [
        ImputedColumn(
            str(r.variable),
            int(r.missing),
            none(r.observed_mean),
            none(r.observed_sd),
            none(r.imputed_mean),
            none(r.imputed_sd),
        )
        for r in found["imputed_summary"].itertuples()
    ]
    events = [f"{r.dep}: {r.meth} {r.out}".strip() for r in found["imputation_events"].itertuples()]
    return columns, list(dict.fromkeys(events))


R_CORRELATIONS = """\
# Correlations pooled over the imputed data sets: M and SD averaged over them, and {coefficient}
# for each pair from miceadds::micombine.cor (Fisher's z, Rubin's rules), on everyone.
variables <- c({columns})
descriptives <- data.frame(
  variable = variables, n = nrow(d),
  mean = rowMeans(sapply(completed, function(x) colMeans(x[variables]))),
  sd = rowMeans(sapply(completed, function(x) sapply(x[variables], sd))), row.names = NULL)
print(descriptives)
pooled <- miceadds::micombine.cor(miceadds::datlist_create(completed), variables = variables,
                                  method = "{method}")
correlations <- data.frame(x = pooled$variable1, y = pooled$variable2, n = nrow(d),
                           r = pooled$r, p = pooled$p)
print(correlations)
"""


def correlation_code(
    variables: list[Variable], method: str, found: ImputationPlan, file: str
) -> Code:
    coefficient = "Spearman's rho" if method == "spearman" else "Pearson r"
    available = analysis_script.correlation_code(variables, method)
    body = R_CORRELATIONS.format(
        columns=quoted([v.column for v in variables]), coefficient=coefficient, method=method
    )
    return Code(
        title="Correlations after multiple imputation",
        r=impute_r(found, file) + body,
        python=PYTHON_IMPUTE + available.python,
        outputs=("descriptives", "correlations"),
        packages=PACKAGES,
    )


R_REGRESSION = """\
# Regression after multiple imputation: {y_label} on each X by itself, fitted in every imputed
# data set and pooled with mice::pool (Rubin's rules), on everyone; r with its 95% CI from
# miceadds::micombine.cor and R squared from mice::pool.r.squared.
y <- {y}
regressions <- do.call(rbind, lapply(c({xs}), function(x) {{
  fits <- mice::as.mira(lapply(completed, function(data) lm(data[[y]] ~ data[[x]])))
  coefs <- summary(mice::pool(fits))
  pair <- miceadds::datlist_create(lapply(completed, function(data) data[c(x, y)]))
  r <- miceadds::micombine.cor(pair, method = "pearson")[1, ]
  data.frame(x = x, n = nrow(d), slope = coefs$estimate[2], slope_se = coefs$std.error[2],
             intercept = coefs$estimate[1], intercept_se = coefs$std.error[1], r = r$r,
             r_low = r$lower95, r_high = r$upper95,
             r_squared = mice::pool.r.squared(fits)[1, "est"], p = coefs$p.value[2])
}}))
print(regressions)
"""


def regression_code(xs: list[Variable], y: Variable, found: ImputationPlan, file: str) -> Code:
    available = analysis_script.regression_code(xs, y)
    body = R_REGRESSION.format(
        y=r_string(y.column), xs=quoted([v.column for v in xs]), y_label=y.label
    )
    return Code(
        title="Regression after multiple imputation",
        r=impute_r(found, file) + body,
        python=PYTHON_IMPUTE + available.python,
        outputs=("regressions",),
        packages=PACKAGES,
    )


R_GROUPS = """\
# Group comparison after multiple imputation: {outcome_label} by {group_label}, on everyone
# whose group is known, with the outcome imputed where it is missing{left_out}
keep <- d[[{group}]] %in% c({values})
sets <- lapply(completed, function(x) {{
  data.frame(group = factor(x[[{group}]][keep], levels = c({values}), labels = c({labels})),
             y = x[[{outcome}]][keep])
}})
groups <- data.frame(group = c({labels}), n = as.vector(table(sets[[1]]$group)),
                     mean = rowMeans(sapply(sets, function(s) tapply(s$y, s$group, mean))),
                     sd = rowMeans(sapply(sets, function(s) tapply(s$y, s$group, sd))))
print(groups)
"""
R_STUDENT = """\
# Student's t test pooled over the imputed data sets (the group coefficient of lm, mice::pool,
# Barnard-Rubin df), signed as the first group minus the second; Cohen's d with the pooled SD
# averaged over the data sets (effectsize).
fits <- mice::as.mira(lapply(sets, function(s) lm(y ~ group, data = s)))
pooled <- summary(mice::pool(fits), conf.int = TRUE)[2, ]
print(pooled)
d_values <- sapply(sets, function(s) effectsize::cohens_d(y ~ group, data = s)$Cohens_d)
test_result <- data.frame(statistic = -pooled$statistic, df1 = pooled$df, df2 = NA,
                          p = pooled$p.value, low = -pooled$conf.high, high = -pooled$conf.low,
                          effect = mean(d_values), effect_low = NA, effect_high = NA,
                          omega = NA, omega_low = NA, omega_high = NA)
print(test_result)
"""
R_ANOVA = """\
# One-way analysis of variance pooled over the imputed data sets (mice::D1, the multivariate
# Wald test of the groups); eta squared and omega squared averaged over them (effectsize).
full <- mice::as.mira(lapply(sets, function(s) lm(y ~ group, data = s)))
empty <- mice::as.mira(lapply(sets, function(s) lm(y ~ 1, data = s)))
wald <- mice::D1(full, empty)$result
print(wald)
etas <- sapply(sets, function(s) effectsize::eta_squared(aov(y ~ group, data = s),
                                                          partial = FALSE)$Eta2)
omegas <- sapply(sets, function(s) effectsize::omega_squared(aov(y ~ group, data = s),
                                                              partial = FALSE)$Omega2)
test_result <- data.frame(statistic = wald[1, "F.value"], df1 = wald[1, "df1"],
                          df2 = wald[1, "df2"], p = wald[1, "P(>F)"], low = NA, high = NA,
                          effect = mean(etas), effect_low = NA, effect_high = NA,
                          omega = mean(omegas), omega_low = NA, omega_high = NA)
print(test_result)
"""


def comparison_plan(
    frame: pd.DataFrame, group: Variable, outcome: Variable, found: ImputationPlan, file: str
) -> ComparisonPlan | None:
    # Group sizes count everyone whose group is known, since the outcome is imputed.
    sizes = [
        (value, text, int((frame[group.column] == value).sum())) for value, text in group.options
    ]
    kept = [(value, text) for value, text, n in sizes if n >= MIN_GROUP]
    if len(kept) < 2:
        return None
    left = [(text, n) for _, text, n in sizes if n < MIN_GROUP]
    shown = ", ".join(f"{text} ({n})" for text, n in left)
    left_out = f".\n# Left out, fewer than {MIN_GROUP} people: {shown}" if left else ""
    kind = STUDENT if len(kept) == 2 else ANOVA
    available = analysis_script.comparison_plan(frame, group, outcome, kind)
    body = R_GROUPS.format(
        group=r_string(group.column),
        outcome=r_string(outcome.column),
        group_label=group.label,
        outcome_label=outcome.label,
        left_out=left_out,
        values=", ".join(number(v) for v, _ in kept),
        labels=", ".join(r_string(text) for _, text in kept),
    ) + (R_STUDENT if kind == STUDENT else R_ANOVA)
    python = PYTHON_IMPUTE + (available.code.python if available else "")
    code = Code(
        title="Group comparison after multiple imputation",
        r=impute_r(found, file) + body,
        python=python,
        outputs=("groups", "test_result"),
        python_footer=available.code.python_footer if available else "",
        packages=(*PACKAGES, "effectsize"),
    )
    return ComparisonPlan(kind, code, left)
