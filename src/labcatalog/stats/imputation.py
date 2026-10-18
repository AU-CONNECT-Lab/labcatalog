from dataclasses import dataclass, field

from labcatalog.stats import analysis_script
from labcatalog.stats.analysis_script import AnalysisData, Code, Variable, r_string
from labcatalog.stats.rbridge import IMPUTATION_PACKAGES as PACKAGES

AVAILABLE = "available"
IMPUTE = "impute"
METHODS = {AVAILABLE: "Available cases", IMPUTE: "Multiple imputation"}
# quickpred keeps the predictors that correlate at least this much with a column or its missingness.
MIN_CORRELATION = 0.1

R_IMPUTE = """# Multiple imputation with mice: {m} imputed data sets by predictive mean matching, seed {seed}.
# Imputed: {what}.
# Each column is predicted by those that correlate at least {mincor} with it or with its
# missingness (quickpred); each score is then computed again from its imputed items.
imputed_columns <- c({columns})
predictors <- mice::quickpred(d[imputed_columns], mincor = {mincor})
imputation <- mice::mice(d[imputed_columns], m = {m}, seed = {seed},
                         predictorMatrix = predictors, printFlag = FALSE)
completed <- lapply(seq_len({m}), function(i) {{
  x <- d
  x[imputed_columns] <- mice::complete(imputation, i)
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
    # Item columns imputed and scored again, numbers imputed as they are, and helpers.
    items: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    auxiliaries: list[str] = field(default_factory=list)
    # Each score column, sum or mean, and its item columns.
    scores: list[tuple[str, str, list[str]]] = field(default_factory=list)

    @property
    def columns(self) -> list[str]:
        return list(dict.fromkeys([*self.items, *self.numbers, *self.auxiliaries]))


def plan(
    data: AnalysisData, keys: list[str], auxiliaries: list[str], m: int, seed: int
) -> ImputationPlan:
    found = ImputationPlan(m, seed)
    scores = {s.key: s for s in data.result.catalog.scores}
    for key in keys:
        if key not in scores:
            found.numbers.append(data.variable(key).column)
            continue
        v = data.score(key, items=True)
        if v.items:
            found.items += [c for c in v.items if c not in found.items]
            found.scores.append((v.column, scores[key].method, v.items))
        else:
            found.numbers.append(v.column)
    found.auxiliaries = [data.score(k).column for k in auxiliaries if k not in keys]
    return found


def impute_r(found: ImputationPlan) -> str:
    parts = ["the items of the chosen scores"] if found.items else []
    if found.numbers:
        parts.append("the chosen numbers")
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
        scores=lines,
    )


def quoted(columns: list[str]) -> str:
    return ", ".join(r_string(c) for c in columns)


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


def correlation_code(variables: list[Variable], method: str, found: ImputationPlan) -> Code:
    coefficient = "Spearman's rho" if method == "spearman" else "Pearson r"
    available = analysis_script.correlation_code(variables, method)
    body = R_CORRELATIONS.format(
        columns=quoted([v.column for v in variables]), coefficient=coefficient, method=method
    )
    return Code(
        title="Correlations after multiple imputation",
        r=impute_r(found) + body,
        python=PYTHON_IMPUTE + available.python,
        outputs=("descriptives", "correlations"),
        packages=PACKAGES,
    )


R_SUMMARY = """\
# The imputed values beside the observed ones, over all imputed data sets, and what mice
# reported doing, such as leaving out a column that another one predicts exactly.
imputed_summary <- do.call(rbind, lapply(imputed_columns, function(column) {{
  seen <- d[[column]]
  drawn <- unlist(imputation$imp[[column]], use.names = FALSE)
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
"""


@dataclass
class ImputedColumn:
    column: str
    missing: int
    observed_mean: float | None
    observed_sd: float | None
    imputed_mean: float | None
    imputed_sd: float | None


def summary_code(found: ImputationPlan) -> Code:
    return Code(
        title="Multiple imputation",
        r=impute_r(found) + R_SUMMARY.format(),
        python=PYTHON_IMPUTE,
        outputs=("imputed_summary", "imputation_events"),
        packages=PACKAGES,
    )


def read_summary(found: dict) -> tuple[list[ImputedColumn], list[str]]:
    columns = [
        ImputedColumn(
            str(r.variable),
            int(r.missing),
            *(analysis_script.none(getattr(r, k)) for k in ("observed_mean", "observed_sd")),
            *(analysis_script.none(getattr(r, k)) for k in ("imputed_mean", "imputed_sd")),
        )
        for r in found["imputed_summary"].itertuples()
    ]
    events = [f"{r.dep}: {r.meth} {r.out}".strip() for r in found["imputation_events"].itertuples()]
    return columns, list(dict.fromkeys(events))


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


def regression_code(xs: list[Variable], y: Variable, found: ImputationPlan) -> Code:
    available = analysis_script.regression_code(xs, y)
    body = R_REGRESSION.format(
        y=r_string(y.column), xs=quoted([v.column for v in xs]), y_label=y.label
    )
    return Code(
        title="Regression after multiple imputation",
        r=impute_r(found) + body,
        python=PYTHON_IMPUTE + available.python,
        outputs=("regressions",),
        packages=PACKAGES,
    )
