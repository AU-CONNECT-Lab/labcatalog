import shutil
import subprocess
from dataclasses import replace
from glob import glob

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from labcatalog.charts import plot_code, views
from labcatalog.gui import analysis_tables
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats.rbridge import ANALYSIS_PACKAGES, r_status

EMS = "example_mood.ems_total@child_w1"
EPS = "example_parent_stress.eps_mean@parent_w1"
GENDER = "item:example_demographics.dem_gender@parent_w1"
FAA = "item:eeg_resting.frontal_alpha_asymmetry@eeg_w1"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


def r_ready() -> bool:
    return rscript() is not None and not r_status(rscript(), ANALYSIS_PACKAGES).missing


needs_r = pytest.mark.skipif(not r_ready(), reason="R with psych and effectsize is not installed")


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


@pytest.fixture
def sample(result):
    return analysis.build_sample(result, ["parent_w1", "child_w1"], True)


def table_one(result, sample, rscript_path=None):
    data = script.AnalysisData(result, sample)
    rows = script.measure_variables(data, script.default_measures(result, sample.datasets), True)
    code = script.table_one_code(sample.datasets, rows)
    frame = data.frame()
    return frame, script.run_code(result, sample, frame, code, rscript_path)


def comparison(result, sample, two_groups, rscript_path=None, t_test=script.WELCH):
    data = script.AnalysisData(result, sample)
    group, outcome = data.item(GENDER), data.score(EMS)
    if two_groups:
        group = replace(group, options=group.options[:2])
    frame = data.frame()
    plan = script.comparison_plan(frame, group, outcome, t_test)
    found, engine = script.run_code(result, sample, frame, plan.code, rscript_path)
    return script.read_comparison(found, plan), engine


def test_table_one_matches_a_direct_calculation(result, sample):
    frame, (found, engine) = table_one(result, sample)
    table = found["table1"]
    assert engine == script.PYTHON
    assert table[table["variable"] == "N"]["n"].tolist() == [len(sample.people)] * 2
    age = table[table["variable"] == "Child age"].iloc[0]
    assert age["mean"] == pytest.approx(frame["dem_age_w1"].mean())
    assert age["sd"] == pytest.approx(frame["dem_age_w1"].std())
    gender = table[table["variable"] == "Child gender"]
    assert gender["level"].tolist() == ["Girl", "Boy", "Another gender"]
    assert gender["n"].sum() == frame["dem_gender_w1"].notna().sum()
    assert gender["percent"].sum() == pytest.approx(100)
    cov = frame[[f"ems_{i}_w1" for i in range(1, 10)]].cov().to_numpy()
    k = cov.shape[0]
    expected = k / (k - 1) * (1 - np.trace(cov) / cov.sum())
    ems = table[table["variable"] == "EMS Total score"].iloc[0]
    assert ems["alpha"] == pytest.approx(expected)
    assert ems["alpha"] == pytest.approx(0.9, abs=0.02)


def test_two_groups_get_welch_and_more_get_anova(result, sample):
    welch, _ = comparison(result, sample, two_groups=True)
    assert welch.test == "welch" and [g.label for g in welch.groups] == ["Girl", "Boy"]
    assert (
        welch.df2 is None and welch.low < welch.groups[0].mean - welch.groups[1].mean < welch.high
    )
    anova, _ = comparison(result, sample, two_groups=False)
    assert anova.test == "anova" and len(anova.groups) == 3
    assert (anova.df1, anova.df2) == (2, sum(g.n for g in anova.groups) - 3)
    assert 0 <= anova.effect < 1


def test_student_uses_equal_variances_and_the_pooled_sd(result, sample):
    found, _ = comparison(result, sample, two_groups=True, t_test=script.STUDENT)
    assert found.test == script.STUDENT
    data = script.AnalysisData(result, sample)
    group, outcome = data.item(GENDER), data.score(EMS)
    frame = data.frame()
    girls = frame.loc[frame[group.column] == 1, outcome.column].dropna()
    boys = frame.loc[frame[group.column] == 2, outcome.column].dropna()
    student = stats.ttest_ind(girls, boys, equal_var=True)
    assert (found.statistic, found.p, found.df1) == pytest.approx(
        (student.statistic, student.pvalue, len(girls) + len(boys) - 2)
    )
    pooled = np.sqrt(
        ((len(girls) - 1) * girls.var() + (len(boys) - 1) * boys.var())
        / (len(girls) + len(boys) - 2)
    )
    assert found.effect == pytest.approx((girls.mean() - boys.mean()) / pooled)


JASP_TTESTS = "C:/Program Files (x86)/JASP/Modules/module_libs/jaspTTests/jaspTTests/R/jaspTTests"
JASP_LIMITS = """\
env <- new.env()
invisible(lazyLoad("{lib}", envir = env))
limits <- get(".confidenceLimitsEffectSizes", envir = env)(
  ncp = {ncp}, df = {df}, alpha.lower = 0.025, alpha.upper = 0.025)
cat(limits$Lower.Limit, limits$Upper.Limit)
"""


@pytest.mark.skipif(
    not r_ready() or not glob(f"{JASP_TTESTS}.rdb"), reason="needs R with the packages and JASP"
)
@pytest.mark.parametrize("t_test", [script.WELCH, script.STUDENT])
def test_the_interval_of_d_is_jasps(result, sample, tmp_path, t_test):
    found, _ = comparison(result, sample, True, t_test=t_test)
    n = [g.n for g in found.groups]
    scale = np.sqrt(n[0] * n[1] / sum(n))
    (tmp_path / "jasp.R").write_text(
        JASP_LIMITS.format(lib=JASP_TTESTS, ncp=float(found.effect * scale), df=found.df1),
        encoding="utf-8",
    )
    done = subprocess.run([rscript(), str(tmp_path / "jasp.R")], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    low, high = (float(v) / scale for v in done.stdout.split())
    assert (found.effect_low, found.effect_high) == pytest.approx((low, high), abs=1e-6)


@needs_r
def test_student_agrees_in_r_and_python(result, sample):
    in_python, _ = comparison(result, sample, True, t_test=script.STUDENT)
    in_r, _ = comparison(result, sample, True, rscript(), t_test=script.STUDENT)
    for field in ("statistic", "df1", "p", "effect"):
        assert getattr(in_r, field) == pytest.approx(getattr(in_python, field), rel=1e-9)


def test_small_groups_are_left_out(result, sample):
    data = script.AnalysisData(result, sample)
    group, outcome = data.item(GENDER), data.score(EMS)
    frame = data.frame()
    frame.loc[frame["dem_gender_w1"] == 3, "dem_gender_w1"] = np.nan
    frame.loc[frame.index[frame["dem_gender_w1"].notna()][0], "dem_gender_w1"] = 3
    plan = script.comparison_plan(frame, group, outcome)
    assert plan.kind == "welch"
    assert plan.left_out == [("Another gender", 1)]
    assert "# Left out, fewer than 2 people: Another gender (1)." in plan.code.r


@needs_r
def test_r_and_python_give_the_same_numbers(result, sample):
    _, (python, _) = table_one(result, sample)
    _, (r, engine) = table_one(result, sample, rscript())
    assert engine == script.R
    numbers = ["n", "mean", "sd", "percent", "alpha"]
    np.testing.assert_allclose(
        r["table1"][numbers].to_numpy(dtype=float),
        python["table1"][numbers].to_numpy(dtype=float),
        rtol=1e-9,
    )
    for two_groups in (True, False):
        in_python, _ = comparison(result, sample, two_groups)
        in_r, _ = comparison(result, sample, two_groups, rscript())
        for field in ("statistic", "df1", "p", "effect"):
            assert getattr(in_r, field) == pytest.approx(getattr(in_python, field), rel=1e-9)
        if two_groups:
            assert (in_r.low, in_r.high) == pytest.approx((in_python.low, in_python.high))
            # Both solve JASP's noncentral t interval, MBESS in R and scipy here.
            assert (in_r.effect_low, in_r.effect_high) == pytest.approx(
                (in_python.effect_low, in_python.effect_high), abs=1e-6
            )
        else:
            assert in_python.effect_low is None and in_python.omega is None
            assert 0 <= in_r.effect_low <= in_r.effect <= in_r.effect_high
            assert in_r.omega_low <= in_r.omega <= in_r.effect


FIGURES = {
    "heatmap": "correlations.png",
    "dots": "correlations.png",
    "regression": "regression.png",
    "groups": "group_comparison.png",
}


def section_scripts(result, sample) -> dict[str, dict[str, str]]:
    # Each section's saved files as the Analysis page builds them, figure code included.
    data = script.AnalysisData(result, sample)
    ems, eps, gender = data.variable(EMS), data.variable(EPS), data.item(GENDER)
    frame = data.frame()
    labels = {ems.column: "EMS", eps.column: "EPS"}
    plan = script.comparison_plan(frame, gender, ems)
    sections = {
        "heatmap": (script.correlation_code([ems, eps]), plot_code.correlation(labels, "r", False)),
        "dots": (script.correlation_code([ems, eps]), plot_code.correlation(labels, "r", True)),
        "regression": (
            script.regression_code([eps], ems),
            plot_code.regression({eps.column: "EPS"}, "EMS"),
        ),
        "groups": (plan.code, plot_code.groups("Gender", "EMS", 3)),
    }
    return {
        name: analysis_tables.section_files(result, sample, frame, code, figure)
        for name, (code, figure) in sections.items()
    }


def written(texts: dict[str, str], folder) -> None:
    folder.mkdir()
    for name, text in texts.items():
        (folder / name).write_text(text, encoding="utf-8")


def test_each_section_script_runs_and_draws_its_figure(result, sample, tmp_path, monkeypatch):
    monkeypatch.setenv("MPLBACKEND", "Agg")
    found = {}
    for name, texts in section_scripts(result, sample).items():
        written(texts, tmp_path / name)
        monkeypatch.chdir(tmp_path / name)
        names: dict = {}
        exec(texts["analysis.py"], names)
        names["plt"].close("all")
        assert (tmp_path / name / FIGURES[name]).stat().st_size > 0
        found[name] = names
    expected = analysis.correlate(
        analysis.values(result, sample, EMS), analysis.values(result, sample, EPS)
    )
    correlation = found["heatmap"]["correlations"].iloc[0]
    assert (correlation["n"], correlation["r"]) == (expected.n, pytest.approx(expected.r))
    fit = analysis.regress(
        analysis.values(result, sample, EPS), analysis.values(result, sample, EMS)
    )
    assert found["regression"]["regressions"].iloc[0]["slope"] == pytest.approx(fit.slope)
    assert found["regression"]["regressions"].iloc[0]["slope_se"] == pytest.approx(fit.slope_se)
    assert list(found["groups"]["groups"]["group"]) == ["Girl", "Boy", "Another gender"]


@needs_r
def test_each_section_script_runs_and_draws_its_figure_in_r(result, sample, tmp_path):
    for name, texts in section_scripts(result, sample).items():
        written(texts, tmp_path / name)
        done = subprocess.run(
            [rscript(), "analysis.R"], cwd=tmp_path / name, capture_output=True, text=True
        )
        assert done.returncode == 0, done.stderr
        assert (tmp_path / name / FIGURES[name]).stat().st_size > 0
        if name == "groups":
            assert "Eta2" in done.stdout


def test_table_one_reads_like_a_paper_table(result, sample):
    _, (found, _) = table_one(result, sample)
    labels = {"parent_w1": "Parent", "child_w1": "Child"}
    columns, rows = analysis_tables.table_one_table(found["table1"], sample.datasets, labels)
    assert [c["label"] for c in columns] == ["Variable", "Parent", "α", "Child", "α"]
    n = str(len(sample.people))
    assert (rows[0]["variable"], rows[0]["d0"], rows[0]["d1"], rows[0]["a0"]) == ("N", n, n, "")
    gender = [r["variable"] for r in rows].index("Child gender")
    assert rows[gender + 1]["variable"] == analysis_tables.INDENT + "Girl"
    assert rows[gender + 1]["d0"].endswith("%)")
    ems = next(r for r in rows if r["variable"] == "EMS Total score")
    assert ems["a1"].startswith(".") and "(" in ems["d1"]


def test_test_tables_name_the_test_and_effect(result, sample):
    welch, _ = comparison(result, sample, two_groups=True)
    columns, [row] = analysis_tables.test_table(welch)
    assert [c["label"] for c in columns] == [
        "Test",
        "t",
        "df",
        "p",
        "d [95% CI]",
        "Difference [95% CI]",
    ]
    assert row["test"] == "Welch's t test"
    assert row["effect"].count("[") == 1
    anova, _ = comparison(result, sample, two_groups=False)
    columns, [row] = analysis_tables.test_table(anova)
    assert [c["label"] for c in columns] == ["Test", "F", "df", "p", "η² [95% CI]", "ω² [95% CI]"]
    assert row["df"] == f"2, {sum(g.n for g in anova.groups) - 3}"
    assert pd.notna(row["p"])


def correlations(result, sample, rscript_path=None, method="pearson"):
    data = script.AnalysisData(result, sample)
    variables = [data.score(EMS), data.score(EPS)]
    code = script.correlation_code(variables, method)
    found, _ = script.run_code(result, sample, data.frame(), code, rscript_path)
    return script.read_correlations(found, [v.column for v in variables])


def test_spearman_matches_scipy_and_r(result, sample):
    ems, eps = analysis.values(result, sample, EMS), analysis.values(result, sample, EPS)
    both = pd.concat([ems, eps], axis=1).dropna()
    expected = stats.spearmanr(both.iloc[:, 0], both.iloc[:, 1])
    _, matrix = correlations(result, sample, method="spearman")
    assert (matrix[1][0].r, matrix[1][0].p) == pytest.approx((expected.statistic, expected.pvalue))
    if r_ready():
        _, in_r = correlations(result, sample, rscript(), method="spearman")
        assert in_r[1][0].r == pytest.approx(expected.statistic)
        assert in_r[1][0].p == pytest.approx(expected.pvalue, rel=1e-3)


def test_summary_correlations_follow_the_project_setting(mock_project):
    config = mock_project / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    assert "  correlation: pearson" in text
    config.write_text(
        text.replace("  correlation: pearson", "  correlation: spearman"), encoding="utf-8"
    )
    found = run_catalog(mock_project)
    assert found.project.config.stats.coefficient() == "Spearman's ρ"
    wave = next(c for c in found.summary.correlations if c.wave == "1")
    i, j = wave.keys.index(EMS), wave.keys.index("example_mood.ems_sadness@child_w1")
    scores = found.scores["child_w1"]
    expected = scores[EMS].corr(scores["example_mood.ems_sadness@child_w1"], method="spearman")
    assert wave.r[i][j] == pytest.approx(expected)


def regressions(result, sample, rscript_path=None):
    data = script.AnalysisData(result, sample)
    x, y = data.score(EPS), data.score(EMS)
    code = script.regression_code([x], y)
    found, _ = script.run_code(result, sample, data.frame(), code, rscript_path)
    return script.read_regressions(found, {x.column: EPS})[EPS]


def test_correlations_and_regression_match_the_summary_numbers(result, sample):
    ems, eps = analysis.values(result, sample, EMS), analysis.values(result, sample, EPS)
    described, matrix = correlations(result, sample)
    expected = analysis.correlate(ems, eps)
    assert described[0][0] == ems.notna().sum()
    assert (matrix[1][0].n, matrix[1][0].r, matrix[1][0].p) == (
        expected.n,
        pytest.approx(expected.r),
        pytest.approx(expected.p),
    )
    assert matrix[0][1] is matrix[1][0] and matrix[0][0].r is None
    fit = regressions(result, sample)
    expected = analysis.regress(eps, ems)
    assert (fit.slope, fit.slope_se, fit.intercept) == pytest.approx(
        (expected.slope, expected.slope_se, expected.intercept)
    )
    assert (fit.correlation.low, fit.correlation.high) == pytest.approx(
        (expected.correlation.low, expected.correlation.high)
    )


@needs_r
def test_correlations_and_regression_agree_in_r_and_python(result, sample):
    _, in_python = correlations(result, sample)
    described, in_r = correlations(result, sample, rscript())
    assert (in_r[1][0].r, in_r[1][0].p) == pytest.approx((in_python[1][0].r, in_python[1][0].p))
    assert in_r[1][0].n == in_python[1][0].n
    py_fit, r_fit = regressions(result, sample), regressions(result, sample, rscript())
    assert (r_fit.slope, r_fit.slope_se, r_fit.correlation.p) == pytest.approx(
        (py_fit.slope, py_fit.slope_se, py_fit.correlation.p)
    )
    assert r_fit.correlation.high == pytest.approx(py_fit.correlation.high, abs=0.006)


def test_an_item_reads_by_its_label_or_else_by_its_text(result):
    age = script.item_variable(result, "item:example_demographics.dem_age@parent_w1")
    assert script.item_label(result, age) == "Child age"
    unnamed = age.model_copy(update={"label": None})
    assert script.item_label(result, unnamed) == "EFB: How old is your child (in years)?"
    choices = views.variable_choices(result, ["eeg_w1"])
    assert choices[FAA] == "EEG: Frontal alpha asymmetry (Wave 1)"


def test_number_items_analyse_beside_scores(result, tmp_path, monkeypatch):
    sample = analysis.build_sample(result, ["child_w1", "eeg_w1"], True)
    choices = views.variable_choices(result, sample.datasets)
    assert FAA in choices and FAA not in views.total_choices(result, sample.datasets)
    # Children link by family under the example's correlate_by.
    eeg = result.datasets["eeg_w1"].frame
    expected = pd.Series(
        pd.to_numeric(eeg["frontal_alpha_asymmetry"]).to_numpy(), index=eeg["pid"].str[:4]
    ).reindex(sample.people)
    pd.testing.assert_series_equal(
        analysis.values(result, sample, FAA), expected, check_names=False
    )
    data = script.AnalysisData(result, sample)
    ems, faa = data.variable(EMS), data.variable(FAA)
    frame = data.frame()
    codes = [script.correlation_code([ems, faa]), script.regression_code([faa], ems)]
    _, python_text = script.script(result, sample, codes)
    assert "frontal_alpha_asymmetry_eeg_w1" in frame.columns
    frame.to_csv(tmp_path / script.DATA_FILE, index=False)
    monkeypatch.chdir(tmp_path)
    names: dict = {}
    exec(python_text, names)
    direct = analysis.correlate(analysis.values(result, sample, EMS), expected)
    found = names["correlations"].iloc[0]
    assert (found["n"], found["r"]) == (direct.n, pytest.approx(direct.r))
    assert names["regressions"].iloc[0]["n"] == direct.n


def test_table_one_offers_number_items_but_starts_without_them(result):
    datasets = ["child_w1", "parent_w1", "eeg_w1"]
    key = "item:eeg_resting.frontal_alpha_asymmetry"
    assert key in script.measures(result, datasets)
    defaults = script.default_measures(result, datasets)
    assert key not in defaults and "item:example_demographics.dem_gender" in defaults
