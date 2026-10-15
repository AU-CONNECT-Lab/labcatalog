import contextlib
import io
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from labcatalog import analysis
from labcatalog.cfa import is_total, run_r
from labcatalog.codegen import number
from labcatalog.pipeline import CatalogResult
from labcatalog.resolve import ResolvedVariable, numbers_in_range
from labcatalog.scoring import score_items

DATA_FILE = "analysis_data.csv"
SCORE = "score"
NUMBER = "number"
CHOICE = "choice"
ITEM_PREFIX = "item:"
MIN_GROUP = 2
R = "R"
PYTHON = "Python"
TABLE_COLUMNS = ("variable", "dataset", "level", "n", "mean", "sd", "percent", "alpha")

R_HEADER = """\
# {title}
# {sample}
# d is the analysis data saved from the Analysis page: one row per person, scores as labcatalog
# computed them, and each score's items reversed where the scale says so.
d <- read.csv({path}, check.names = FALSE)
"""
PYTHON_HEADER = """\
# {title}
# {sample}
# d is the analysis data saved from the Analysis page: one row per person, scores as labcatalog
# computed them, and each score's items reversed where the scale says so.
import itertools

import numpy as np
import pandas as pd
from scipy import stats

d = pd.read_csv({path})
"""
R_TABLE_ONE = """\
# Table 1: N in each dataset; M (SD) for numbers and scores, with alpha; n (%) for answer options.
alpha <- function(items) {{
  items <- na.omit(items)
  k <- ncol(items)
  k / (k - 1) * (1 - sum(apply(items, 2, var)) / var(rowSums(items)))
}}
n_row <- function(dataset, present) {{
  data.frame(variable = "N", dataset = dataset, level = "", n = sum(present), mean = NA, sd = NA,
             percent = NA, alpha = NA)
}}
number_row <- function(variable, dataset, x, alpha = NA) {{
  data.frame(variable = variable, dataset = dataset, level = "", n = sum(!is.na(x)),
             mean = mean(x, na.rm = TRUE), sd = sd(x, na.rm = TRUE), percent = NA, alpha = alpha)
}}
choice_rows <- function(variable, dataset, x, levels) {{
  n <- vapply(levels, function(value) sum(x == value, na.rm = TRUE), numeric(1))
  data.frame(variable = variable, dataset = dataset, level = names(levels), n = n, mean = NA,
             sd = NA, percent = 100 * n / sum(!is.na(x)), alpha = NA)
}}
table1 <- rbind(
{rows}
)
rownames(table1) <- NULL
print(table1)
"""
PYTHON_TABLE_ONE = """\
# Table 1: N in each dataset; M (SD) for numbers and scores, with alpha; n (%) for answer options.
def alpha(items):
    items = items.dropna()
    k = items.shape[1]
    return k / (k - 1) * (1 - items.var().sum() / items.sum(axis=1).var())


def n_row(dataset, present):
    return [dict(variable="N", dataset=dataset, level="", n=present.sum(), mean=np.nan,
                 sd=np.nan, percent=np.nan, alpha=np.nan)]


def number_row(variable, dataset, x, alpha=np.nan):
    return [dict(variable=variable, dataset=dataset, level="", n=x.notna().sum(), mean=x.mean(),
                 sd=x.std(), percent=np.nan, alpha=alpha)]


def choice_rows(variable, dataset, x, levels):
    valid = x.notna().sum()
    return [dict(variable=variable, dataset=dataset, level=label, n=(x == value).sum(),
                 mean=np.nan, sd=np.nan, percent=100 * (x == value).sum() / valid if valid else np.nan,
                 alpha=np.nan) for label, value in levels.items()]


table1 = pd.DataFrame([
{rows}
])
print(table1)
"""
R_CORRELATIONS = """\
# Correlations: M and SD of each score, then Pearson r for each pair on everyone with both scores.
scores <- c({columns})
print(data.frame(score = scores, n = colSums(!is.na(d[scores])),
                 mean = colMeans(d[scores], na.rm = TRUE),
                 sd = apply(d[scores], 2, sd, na.rm = TRUE), row.names = NULL))
correlations <- do.call(rbind, lapply(combn(scores, 2, simplify = FALSE), function(pair) {{
  test <- cor.test(d[[pair[1]]], d[[pair[2]]])
  data.frame(x = pair[1], y = pair[2], n = sum(complete.cases(d[pair])),
             r = unname(test$estimate), p = test$p.value)
}}))
print(correlations)
"""
PYTHON_CORRELATIONS = """\
# Correlations: M and SD of each score, then Pearson r for each pair on everyone with both scores.
scores = [{columns}]
print(d[scores].agg(["count", "mean", "std"]).T)
rows = []
for x, y in itertools.combinations(scores, 2):
    both = d[[x, y]].dropna()
    test = stats.pearsonr(both[x], both[y])
    rows.append(dict(x=x, y=y, n=len(both), r=test.statistic, p=test.pvalue))
correlations = pd.DataFrame(rows)
print(correlations)
"""
R_REGRESSION = """\
# Regression: {y_label} on each X by itself (simple linear regression).
y <- {y}
regressions <- do.call(rbind, lapply(c({xs}), function(x) {{
  fit <- lm(d[[y]] ~ d[[x]])
  coefs <- summary(fit)$coefficients
  data.frame(x = x, n = nobs(fit), slope = coefs[2, 1], slope_se = coefs[2, 2],
             intercept = coefs[1, 1], intercept_se = coefs[1, 2],
             r_squared = summary(fit)$r.squared, p = coefs[2, 4])
}}))
print(regressions)
"""
PYTHON_REGRESSION = """\
# Regression: {y_label} on each X by itself (simple linear regression).
y = {y}
rows = []
for x in [{xs}]:
    both = d[[x, y]].dropna()
    fit = stats.linregress(both[x], both[y])
    rows.append(dict(x=x, n=len(both), slope=fit.slope, slope_se=fit.stderr,
                     intercept=fit.intercept, intercept_se=fit.intercept_stderr,
                     r_squared=fit.rvalue ** 2, p=fit.pvalue))
regressions = pd.DataFrame(rows)
print(regressions)
"""
R_GROUPS = """\
# Group comparison: {outcome_label} by {group_label}.{left_out}
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
# Welch's t test (unequal variances) and Cohen's d with the pooled SD.
test <- t.test(y ~ group)
print(test)
pooled_sd <- sqrt(sum((groups$n - 1) * groups$sd^2) / (sum(groups$n) - 2))
cohens_d <- (groups$mean[1] - groups$mean[2]) / pooled_sd
cat("Cohen's d:", cohens_d, "\\n")
"""
R_ANOVA = """\
# One-way analysis of variance and eta squared.
anova_table <- summary(aov(y ~ group))[[1]]
print(anova_table)
eta_squared <- anova_table[["Sum Sq"]][1] / sum(anova_table[["Sum Sq"]])
cat("eta squared:", eta_squared, "\\n")
"""
PYTHON_GROUPS = """\
# Group comparison: {outcome_label} by {group_label}.{left_out}
levels = [{labels}]
group = d[{group}].map({{{mapping}}})
y = d[{outcome}]
keep = group.notna() & y.notna()
group, y = group[keep], y[keep]
groups = pd.DataFrame(dict(group=levels, n=[(group == g).sum() for g in levels],
                           mean=[y[group == g].mean() for g in levels],
                           sd=[y[group == g].std() for g in levels]))
print(groups)
"""
PYTHON_WELCH = """\
# Welch's t test (unequal variances) and Cohen's d with the pooled SD.
test = stats.ttest_ind(y[group == levels[0]], y[group == levels[1]], equal_var=False)
low, high = test.confidence_interval()
print(test, "95% CI of the difference:", low, high)
pooled_sd = np.sqrt(((groups["n"] - 1) * groups["sd"] ** 2).sum() / (groups["n"].sum() - 2))
cohens_d = (groups["mean"][0] - groups["mean"][1]) / pooled_sd
print("Cohen's d:", cohens_d)
"""
PYTHON_ANOVA = """\
# One-way analysis of variance and eta squared.
test = stats.f_oneway(*[y[group == g] for g in levels])
print(test)
grand = y.mean()
eta_squared = (groups["n"] * (groups["mean"] - grand) ** 2).sum() / ((y - grand) ** 2).sum()
print("eta squared:", eta_squared)
"""
R_TEST_OUT = {
    "welch": "test_result <- data.frame(statistic = unname(test$statistic), "
    "df1 = unname(test$parameter), df2 = NA, p = test$p.value, effect = cohens_d, "
    "low = test$conf.int[1], high = test$conf.int[2])",
    "anova": 'test_result <- data.frame(statistic = anova_table[["F value"]][1], '
    'df1 = anova_table[["Df"]][1], df2 = anova_table[["Df"]][2], '
    'p = anova_table[["Pr(>F)"]][1], effect = eta_squared, low = NA, high = NA)',
}
PYTHON_TEST_OUT = {
    "welch": "test_result = pd.DataFrame([dict(statistic=test.statistic, df1=test.df, df2=np.nan, "
    "p=test.pvalue, effect=cohens_d, low=low, high=high)])",
    "anova": "test_result = pd.DataFrame([dict(statistic=test.statistic, df1=len(levels) - 1, "
    "df2=len(y) - len(levels), p=test.pvalue, effect=eta_squared, low=np.nan, high=np.nan)])",
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
    left_out: list[tuple[str, int]] = field(default_factory=list)


class AnalysisData:
    # The columns one analysis reads, aligned to the people of the sample.
    def __init__(self, result: CatalogResult, sample: analysis.Sample) -> None:
        self.result = result
        self.sample = sample
        self.columns: dict[str, pd.Series] = {}

    def score(self, key: str) -> Variable:
        score = next(s for s in self.result.catalog.scores if s.key == key)
        instrument = self.result.project.instruments[score.instrument_id]
        definition = next(s for s in instrument.scores if s.id == score.score_id)
        column = f"{score.score_id}_{score.dataset}"
        self.columns[column] = analysis.values(self.result, self.sample, key)
        items = score_items(self.result.datasets[score.dataset], score)
        names = [self.column_name(score.dataset, c) for c in items.columns]
        for name, source in zip(names, items.columns, strict=True):
            self.columns[name] = self.align(score.dataset, items[source].to_numpy(dtype=float))
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
        loaded = self.result.datasets[variable.dataset]
        numbers = loaded.numbers(variable.column)
        options = [(float(o.value), o.label) for o in variable.response_options]
        if variable.type == CHOICE:
            valid = numbers.where(numbers.isin([value for value, _ in options]))
        else:
            valid = numbers.where(numbers_in_range(numbers, variable))
        column = self.column_name(variable.dataset, variable.column)
        self.columns[column] = self.align(variable.dataset, valid.to_numpy(dtype=float))
        instrument = self.result.project.instruments[variable.instrument_id]
        return Variable(
            key=key,
            label=f"{abbreviation(instrument)}: {next(iter(variable.text.values()))}",
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
        keys = analysis.link_keys(self.result, dataset)
        keep = analysis.linkable(keys)
        return pd.Series(values[keep], index=keys.to_numpy()[keep]).reindex(self.sample.people)

    def frame(self) -> pd.DataFrame:
        presence = {}
        for name in self.sample.datasets:
            keys = analysis.link_keys(self.result, name)
            found = set(keys[analysis.linkable(keys)])
            presence[f"in_{name}"] = [int(p in found) for p in self.sample.people]
        frame = pd.DataFrame(
            {link_name(self.result): self.sample.people, **presence}, index=self.sample.people
        )
        return pd.concat([frame, pd.DataFrame(self.columns)], axis=1).reset_index(drop=True)


def abbreviation(instrument) -> str:
    return instrument.abbreviation or instrument.name


def link_name(result: CatalogResult) -> str:
    by = result.project.config.stats.correlate_by
    return "id" if by in ("id", "none") else by


def item_key(variable: ResolvedVariable) -> str:
    return f"{ITEM_PREFIX}{variable.instrument_id}.{variable.item_id}@{variable.dataset}"


def item_variable(result: CatalogResult, key: str) -> ResolvedVariable:
    return next(v for v in result.catalog.variables if item_key(v) == key)


def demographic_items(result: CatalogResult, datasets: list[str]) -> list[ResolvedVariable]:
    instruments = result.project.instruments
    return [
        v
        for name in datasets
        for v in result.catalog.variables_for(name)
        if instruments[v.instrument_id].kind == "demographics" and v.type in (CHOICE, NUMBER)
    ]


def measures(result: CatalogResult, datasets: list[str]) -> dict[str, str]:
    # What Table 1 can show, across the chosen files: demographic items, then scores.
    found = {}
    for v in demographic_items(result, datasets):
        instrument = result.project.instruments[v.instrument_id]
        text = next(iter(v.text.values()))
        found[f"{ITEM_PREFIX}{v.instrument_id}.{v.item_id}"] = f"{abbreviation(instrument)}: {text}"
    for name in datasets:
        for s in result.catalog.scores_for(name):
            instrument = result.project.instruments[s.instrument_id]
            found[f"{s.instrument_id}.{s.score_id}"] = f"{abbreviation(instrument)} {s.label}"
    return found


def default_measures(result: CatalogResult, datasets: list[str]) -> list[str]:
    instruments = result.project.instruments
    return [
        key
        for key in measures(result, datasets)
        if key.startswith(ITEM_PREFIX)
        or is_total(instruments[key.split(".", 1)[0]], key.split(".", 1)[1])
    ]


def measure_variables(
    data: AnalysisData, keys: list[str]
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
                found.append(data.score(f"{key}@{name}"))
        if found:
            rows.append((found[0].label, found))
    return rows


def group_choices(result: CatalogResult, datasets: list[str], labels: dict[str, str]) -> dict[str, str]:
    instruments = result.project.instruments
    return {
        item_key(v): f"{abbreviation(instruments[v.instrument_id])}: "
        f"{next(iter(v.text.values()))} ({labels[v.dataset]})"
        for v in demographic_items(result, datasets)
        if v.type == CHOICE
    }


def r_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def headers(result: CatalogResult, sample: analysis.Sample, path: str) -> tuple[str, str]:
    matched = link_name(result)
    where = ", ".join(sample.datasets)
    title = f"Analysis of {result.project.config.project.name}, written by labcatalog."
    text = f"Sample: {len(sample.people)} people in {where}, matched by {matched}."
    return (
        R_HEADER.format(title=title, sample=text, path=r_string(path)),
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
                levels = ", ".join(f"{r_string(text)} = {number(value)}" for value, text in v.options)
                py_levels = ", ".join(f"{r_string(text)}: {number(value)}" for value, text in v.options)
                r_rows.append(f"  choice_rows({args}, c({levels}))")
                py_rows.append(f"    *choice_rows({py_args}, {{{py_levels}}}),")
            elif v.items:
                items = ", ".join(r_string(c) for c in v.items)
                r_rows.append(f"  number_row({args}, alpha(d[c({items})]))")
                py_rows.append(f"    *number_row({py_args}, alpha(d[[{items}]])),")
            else:
                r_rows.append(f"  number_row({args})")
                py_rows.append(f"    *number_row({py_args}),")
    return Code(
        title="Table 1",
        r=R_TABLE_ONE.format(rows=",\n".join(r_rows)),
        python=PYTHON_TABLE_ONE.format(rows="\n".join(py_rows)),
        outputs=("table1",),
    )


def correlation_code(variables: list[Variable]) -> Code:
    columns = ", ".join(r_string(v.column) for v in variables)
    return Code(
        title="Correlations",
        r=R_CORRELATIONS.format(columns=columns),
        python=PYTHON_CORRELATIONS.format(columns=columns),
        outputs=("correlations",),
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


def group_sizes(frame: pd.DataFrame, group: Variable, outcome: Variable) -> list[tuple[float, str, int]]:
    both = frame[[group.column, outcome.column]].dropna()
    return [(value, text, int((both[group.column] == value).sum())) for value, text in group.options]


def comparison_plan(
    frame: pd.DataFrame, group: Variable, outcome: Variable
) -> ComparisonPlan | None:
    sizes = group_sizes(frame, group, outcome)
    kept = [(value, text) for value, text, n in sizes if n >= MIN_GROUP]
    if len(kept) < 2:
        return None
    left = [(text, n) for _, text, n in sizes if n < MIN_GROUP]
    shown = ", ".join(f"{text} ({n})" for text, n in left)
    left_out = f"\n# Left out, fewer than {MIN_GROUP} people: {shown}." if left else ""
    kind = "welch" if len(kept) == 2 else "anova"
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
    code = Code(
        title="Group comparison",
        r=r + (R_WELCH if kind == "welch" else R_ANOVA),
        python=python + (PYTHON_WELCH if kind == "welch" else PYTHON_ANOVA),
        outputs=("groups", "test_result"),
        r_footer=R_TEST_OUT[kind],
        python_footer=PYTHON_TEST_OUT[kind],
    )
    return ComparisonPlan(kind, code, left)


def script(result: CatalogResult, sample: analysis.Sample, codes: list[Code]) -> tuple[str, str]:
    r_head, py_head = headers(result, sample, DATA_FILE)
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
        r_head, py_head = headers(result, sample, (folder / DATA_FILE).as_posix())
        if rscript:
            writes = [
                f"write.csv({name}, {r_string((folder / f'{name}.csv').as_posix())}, row.names = FALSE)"
                for name in code.outputs
            ]
            path = folder / "analysis.R"
            path.write_text(
                "\n".join([r_head, code.r, code.r_footer, *writes]), encoding="utf-8"
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
        left_out=plan.left_out,
    )


def none(value) -> float | None:
    return None if pd.isna(value) else float(value)
