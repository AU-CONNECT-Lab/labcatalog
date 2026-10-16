import shutil
import subprocess
from dataclasses import replace
from glob import glob

import numpy as np
import pandas as pd
import pytest

from labcatalog.gui import analysis_tables
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats.rbridge import ANALYSIS_PACKAGES, r_status

EMS = "example_mood.ems_total@child_w1"
EPS = "example_parent_stress.eps_mean@parent_w1"
GENDER = "item:example_demographics.dem_gender@parent_w1"


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


def comparison(result, sample, two_groups, rscript_path=None):
    data = script.AnalysisData(result, sample)
    group, outcome = data.item(GENDER), data.score(EMS)
    if two_groups:
        group = replace(group, options=group.options[:2])
    frame = data.frame()
    plan = script.comparison_plan(frame, group, outcome)
    found, engine = script.run_code(result, sample, frame, plan.code, rscript_path)
    return script.read_comparison(found, plan), engine


def test_table_one_matches_a_direct_calculation(result, sample):
    frame, (found, engine) = table_one(result, sample)
    table = found["table1"]
    assert engine == script.PYTHON
    assert table[table["variable"] == "N"]["n"].tolist() == [len(sample.people)] * 2
    age = table[table["variable"] == "EFB: How old is your child (in years)?"].iloc[0]
    assert age["mean"] == pytest.approx(frame["dem_age_w1"].mean())
    assert age["sd"] == pytest.approx(frame["dem_age_w1"].std())
    gender = table[table["variable"] == "EFB: What is your child's gender?"]
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
            # pingouin rounds this interval to two decimals.
            assert (in_r.low, in_r.high) == pytest.approx(
                (in_python.low, in_python.high), abs=0.006
            )
            # effectsize uses the noncentral t, pingouin an approximation.
            assert (in_r.effect_low, in_r.effect_high) == pytest.approx(
                (in_python.effect_low, in_python.effect_high), abs=0.01
            )
        else:
            assert in_python.effect_low is None and in_python.omega is None
            assert 0 <= in_r.effect_low <= in_r.effect <= in_r.effect_high
            assert in_r.omega_low <= in_r.omega <= in_r.effect


def page(result, sample):
    return script.page_script(
        result,
        sample,
        scores=[EMS, EPS],
        xs=[EPS],
        y=EMS,
        group=GENDER,
        outcome=EMS,
    )


def test_the_page_script_runs_and_matches_the_page(result, sample, tmp_path, monkeypatch):
    r_text, python_text, frame = page(result, sample)
    for title in ("# Correlations", "# Regression", "# Group comparison"):
        assert title in r_text and title in python_text
    frame.to_csv(tmp_path / script.DATA_FILE, index=False)
    monkeypatch.chdir(tmp_path)
    names: dict = {}
    exec(python_text, names)
    expected = analysis.correlate(
        analysis.values(result, sample, EMS), analysis.values(result, sample, EPS)
    )
    found = names["correlations"].iloc[0]
    assert (found["n"], found["r"]) == (expected.n, pytest.approx(expected.r))
    fit = analysis.regress(
        analysis.values(result, sample, EPS), analysis.values(result, sample, EMS)
    )
    assert names["regressions"].iloc[0]["slope"] == pytest.approx(fit.slope)
    assert names["regressions"].iloc[0]["slope_se"] == pytest.approx(fit.slope_se)
    assert list(names["groups"]["group"]) == ["Girl", "Boy", "Another gender"]


@needs_r
def test_the_page_script_runs_in_r(result, sample, tmp_path):
    r_text, _, frame = page(result, sample)
    frame.to_csv(tmp_path / script.DATA_FILE, index=False)
    (tmp_path / "analysis.R").write_text(r_text, encoding="utf-8")
    done = subprocess.run([rscript(), "analysis.R"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "Eta2" in done.stdout


def test_table_one_reads_like_a_paper_table(result, sample):
    _, (found, _) = table_one(result, sample)
    labels = {"parent_w1": "Parent", "child_w1": "Child"}
    columns, rows = analysis_tables.table_one_table(found["table1"], sample.datasets, labels)
    assert [c["label"] for c in columns] == ["Variable", "Parent", "α", "Child", "α"]
    n = str(len(sample.people))
    assert (rows[0]["variable"], rows[0]["d0"], rows[0]["d1"], rows[0]["a0"]) == ("N", n, n, "")
    gender = [r["variable"] for r in rows].index("EFB: What is your child's gender?")
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


def correlations(result, sample, rscript_path=None):
    data = script.AnalysisData(result, sample)
    variables = [data.score(EMS), data.score(EPS)]
    code = script.correlation_code(variables)
    found, _ = script.run_code(result, sample, data.frame(), code, rscript_path)
    return script.read_correlations(found, [v.column for v in variables])


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
    # pingouin rounds the interval of r to two decimals.
    assert fit.correlation.low == pytest.approx(expected.correlation.low, abs=0.006)


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
