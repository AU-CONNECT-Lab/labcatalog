from dataclasses import dataclass

import pandas as pd

from labcatalog.pipeline import CatalogResult
from labcatalog.reports.codegen import number
from labcatalog.stats import analysis
from labcatalog.stats.analysis_script import (
    CHOICE,
    MIN_GROUP,
    AnalysisData,
    Code,
    Variable,
    link_name,
    measure_variables,
    none,
    r_string,
)
from labcatalog.stats.summary import wave_order

RETURNED = "returned_next_wave"
STAYED = "Returned"
LEFT = "Did not return"
GROUP_COLUMNS = [
    "variable",
    "level",
    "returned_n",
    "returned_mean",
    "returned_sd",
    "left_n",
    "left_mean",
    "left_sd",
    "returned_percent",
    "left_percent",
]
TEST_COLUMNS = ["variable", "test", "statistic", "df", "p", "effect", "small"]

ABOUT = """\
# Attrition: the {unit} at Wave {first} who took part again at Wave {second} against those who
# did not, on their Wave {first} values. Numbers and scores: n, M and SD, {t_test}.
# Answer options: n (%) and Pearson's chi-squared test without continuity correction, as
# JASP's contingency tables give it.
"""
T_TESTS = {
    "welch": "Welch's t test and Cohen's d with the mean of the two group variances",
    "student": "Student's t test and Cohen's d with the pooled SD",
}
# R's t.test and effectsize, then pingouin's ttest and d, for each test.
T_CODE = {
    "welch": (
        "FALSE",
        "FALSE",
        "True",
        "(stay.mean() - left.mean()) / np.sqrt((stay.var() + left.var()) / 2)",
    ),
    "student": ("TRUE", "TRUE", "False", 'pg.compute_effsize(stay, left, eftype="cohen")'),
}
R_ATTRITION = """\
returned <- factor(d[[{returned}]], levels = c(1, 0), labels = c({stayed}, {left}))
groups <- NULL
tests <- data.frame(variable = character(), test = character(), statistic = numeric(),
                    df = numeric(), p = numeric(), effect = numeric(), small = logical())
number_rows <- function(variable, x, test) {{
  keep <- !is.na(x) & !is.na(returned)
  g <- returned[keep]
  y <- x[keep]
  stay <- y[g == {stayed}]
  left <- y[g == {left}]
  groups <<- rbind(groups, data.frame(
    variable = variable, level = "", returned_n = length(stay), returned_mean = mean(stay),
    returned_sd = sd(stay), left_n = length(left), left_mean = mean(left), left_sd = sd(left),
    returned_percent = NA, left_percent = NA))
  if (test) {{
    t_test <- t.test(y ~ g, var.equal = {var_equal})
    effect <- effectsize::cohens_d(y ~ g, pooled_sd = {pooled})
    tests <<- rbind(tests, data.frame(
      variable = variable, test = "t", statistic = unname(t_test$statistic),
      df = unname(t_test$parameter), p = t_test$p.value, effect = effect$Cohens_d, small = FALSE))
  }}
}}
choice_rows <- function(variable, x, levels, test) {{
  keep <- !is.na(x) & !is.na(returned)
  answer <- factor(x[keep], levels = levels, labels = names(levels))
  counts <- table(answer, returned[keep])
  groups <<- rbind(groups, data.frame(
    variable = variable, level = rownames(counts), returned_n = counts[, 1], returned_mean = NA,
    returned_sd = NA, left_n = counts[, 2], left_mean = NA, left_sd = NA,
    returned_percent = 100 * counts[, 1] / sum(counts[, 1]),
    left_percent = 100 * counts[, 2] / sum(counts[, 2]), row.names = NULL))
  if (test) {{
    chi <- suppressWarnings(chisq.test(counts[rowSums(counts) > 0, , drop = FALSE],
                                       correct = FALSE))
    tests <<- rbind(tests, data.frame(
      variable = variable, test = "chi2", statistic = unname(chi$statistic),
      df = unname(chi$parameter), p = chi$p.value, effect = NA, small = any(chi$expected < 5)))
  }}
}}
{rows}
print(groups)
print(tests)
"""
PYTHON_ATTRITION = """\
returned = d[{returned}].map({{1: {stayed}, 0: {left}}})
groups, tests = [], []


def number_rows(variable, x, test):
    data = pd.DataFrame(dict(g=returned, y=x)).dropna()
    stay = data.loc[data["g"] == {stayed}, "y"]
    left = data.loc[data["g"] == {left}, "y"]
    groups.append(dict(variable=variable, level="", returned_n=len(stay),
                       returned_mean=stay.mean(), returned_sd=stay.std(), left_n=len(left),
                       left_mean=left.mean(), left_sd=left.std()))
    if test:
        t_test = pg.ttest(stay, left, correction={correction})
        effect = {effect}
        tests.append(dict(variable=variable, test="t", statistic=t_test["T"].iloc[0],
                          df=t_test["dof"].iloc[0], p=t_test["p_val"].iloc[0], effect=effect,
                          small=False))


def choice_rows(variable, x, levels, test):
    answer = x.map({{value: label for label, value in levels.items()}})
    data = pd.DataFrame(dict(g=returned, answer=answer)).dropna()
    counts = pd.crosstab(data["answer"], data["g"]).reindex(
        index=list(levels), columns=[{stayed}, {left}], fill_value=0)
    shares = 100 * counts / counts.sum()
    for level in counts.index:
        groups.append(dict(variable=variable, level=level,
                           returned_n=counts.loc[level, {stayed}],
                           left_n=counts.loc[level, {left}],
                           returned_percent=shares.loc[level, {stayed}],
                           left_percent=shares.loc[level, {left}]))
    if test:
        expected, _, found = pg.chi2_independence(data, x="answer", y="g", correction=False)
        pearson = found[found["test"] == "pearson"].iloc[0]
        tests.append(dict(variable=variable, test="chi2", statistic=pearson["chi2"],
                          df=pearson["dof"], p=pearson["pval"], effect=np.nan,
                          small=bool((expected < 5).to_numpy().any())))


{rows}
groups = pd.DataFrame(groups, columns={group_columns})
tests = pd.DataFrame(tests, columns={test_columns})
print(groups)
print(tests)
"""


@dataclass
class Plan:
    first: str
    second: str
    stayed: int
    left: int
    unit: str
    labels: list[str]
    sample: analysis.Sample
    frame: pd.DataFrame
    code: Code


@dataclass
class Row:
    level: str
    returned_n: int
    left_n: int
    returned_mean: float | None = None
    returned_sd: float | None = None
    left_mean: float | None = None
    left_sd: float | None = None
    returned_percent: float | None = None
    left_percent: float | None = None


@dataclass
class Test:
    test: str
    statistic: float
    df: float
    p: float
    effect: float | None
    small: bool


@dataclass
class Compared:
    label: str
    rows: list[Row]
    test: Test | None


def next_wave(result: CatalogResult, study: str, wave: str) -> str | None:
    waves = sorted(
        {d.wave for d in result.project.config.datasets if d.study == study}, key=wave_order
    )
    later = waves[waves.index(wave) + 1 :]
    return later[0] if later else None


def wave_files(result: CatalogResult, study: str, wave: str) -> list[str]:
    return [
        d.name
        for d in result.project.config.datasets
        if (d.study, d.wave) == (study, wave) and d.name in result.datasets
    ]


def unit(result: CatalogResult) -> str:
    matched = link_name(result)
    return "participants" if matched == "id" else f"{matched} groups"


def plan(result: CatalogResult, study: str, wave: str, keys: list[str]) -> Plan | None:
    # Everyone with data at a wave, split by whether any file of the next wave has them.
    second = next_wave(result, study, wave)
    if second is None:
        return None
    first, then = wave_files(result, study, wave), wave_files(result, study, second)
    # Both waves together, so a group taken person by person is so in both.
    both = analysis.build_sample(result, first + then, intersect=False)
    sample = analysis.within(both, first)
    later = set(analysis.within(both, then).people)
    data = AnalysisData(result, sample)
    # A variable in several files of the wave gets a row per file, as reporters may differ.
    variables = [
        (label if len(found) == 1 else f"{label} ({v.dataset})", v)
        for label, found in measure_variables(data, keys)
        for v in found
    ]
    frame = data.frame()
    frame[RETURNED] = [int(p in later) for p in sample.people]
    stayed = int(frame[RETURNED].sum())
    if not variables or min(stayed, len(frame) - stayed) < MIN_GROUP:
        return None
    lines = [call(frame, label, v) for label, v in variables]
    fields = dict(returned=r_string(RETURNED), stayed=r_string(STAYED), left=r_string(LEFT))
    t_test = result.project.config.stats.t_test
    var_equal, pooled, correction, effect = T_CODE[t_test]
    about = ABOUT.format(unit=unit(result), first=wave, second=second, t_test=T_TESTS[t_test])
    r_rows = "\n".join(r for r, _ in lines)
    python_rows = "\n".join(p for _, p in lines)
    code = Code(
        title="Attrition",
        r=about + R_ATTRITION.format(rows=r_rows, var_equal=var_equal, pooled=pooled, **fields),
        python=about
        + PYTHON_ATTRITION.format(
            rows=python_rows,
            group_columns=GROUP_COLUMNS,
            test_columns=TEST_COLUMNS,
            correction=correction,
            effect=effect,
            **fields,
        ),
        outputs=("groups", "tests"),
        packages=("effectsize",),
    )
    return Plan(
        first=wave,
        second=second,
        stayed=stayed,
        left=len(frame) - stayed,
        unit=unit(result),
        labels=[label for label, _ in variables],
        sample=sample,
        frame=frame,
        code=code,
    )


def call(frame: pd.DataFrame, label: str, v: Variable) -> tuple[str, str]:
    stayed = frame.loc[frame[RETURNED] == 1, v.column].dropna()
    left = frame.loc[frame[RETURNED] == 0, v.column].dropna()
    enough = min(len(stayed), len(left)) >= MIN_GROUP
    if v.kind == CHOICE:
        test = enough and pd.concat([stayed, left]).nunique() > 1
        levels = ", ".join(f"{r_string(text)} = {number(value)}" for value, text in v.options)
        py_levels = ", ".join(f"{r_string(text)}: {number(value)}" for value, text in v.options)
        return (
            f"choice_rows({r_string(label)}, d[[{r_string(v.column)}]], c({levels}), "
            f"{'TRUE' if test else 'FALSE'})",
            f"choice_rows({r_string(label)}, d[{r_string(v.column)}], {{{py_levels}}}, {test})",
        )
    # Welch's test needs some spread in at least one group.
    test = enough and max(stayed.nunique(), left.nunique()) > 1
    return (
        f"number_rows({r_string(label)}, d[[{r_string(v.column)}]], {'TRUE' if test else 'FALSE'})",
        f"number_rows({r_string(label)}, d[{r_string(v.column)}], {test})",
    )


def read(found: dict[str, pd.DataFrame], labels: list[str]) -> list[Compared]:
    groups, tests = found["groups"], found["tests"]
    compared = []
    for label in labels:
        part = groups[groups["variable"] == label]
        rows = [
            Row(
                level="" if pd.isna(r.level) else str(r.level),
                returned_n=int(r.returned_n),
                left_n=int(r.left_n),
                returned_mean=none(r.returned_mean),
                returned_sd=none(r.returned_sd),
                left_mean=none(r.left_mean),
                left_sd=none(r.left_sd),
                returned_percent=none(r.returned_percent),
                left_percent=none(r.left_percent),
            )
            for r in part.itertuples()
        ]
        hit = tests[tests["variable"] == label]
        test = None
        if not hit.empty:
            t = hit.iloc[0]
            test = Test(
                test=str(t["test"]),
                statistic=float(t["statistic"]),
                df=float(t["df"]),
                p=float(t["p"]),
                effect=none(t["effect"]),
                small=bool(t["small"]),
            )
        compared.append(Compared(label, rows, test))
    return compared
