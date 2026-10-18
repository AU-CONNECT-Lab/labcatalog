from pathlib import Path

import pandas as pd
import pytest
from scipy import stats

from labcatalog.charts import views
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from tests.test_analysis_script import needs_r, rscript

FILES = ["child_w1", "pilot_w1"]
TOTAL = "example_mood.ems_total@child_w1+pilot_w1"
SADNESS = "example_mood.ems_sadness@child_w1+pilot_w1"


@pytest.fixture
def result(pilot_project: Path):
    # Matched by ID, so every row of the pilot's copy of child_w1 is in the sample.
    config = pilot_project / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("correlate_by: family", "correlate_by: id"), encoding="utf-8")
    return run_catalog(pilot_project)


@pytest.fixture
def sample(result):
    return analysis.build_sample(result, FILES, True)


def test_people_of_several_studies_stack(result, sample):
    one = analysis.build_sample(result, ["child_w1"], True)
    # Every file of one's own study, not every file of every study.
    assert len(sample.people) == 2 * len(one.people)
    assert analysis.values(result, sample, analysis.STUDY_KEY).value_counts().to_dict() == {
        1.0: len(one.people),
        2.0: len(one.people),
    }


def test_variables_pool_when_every_study_has_them_once(result):
    choices = views.variable_choices(result, FILES)
    assert TOTAL in choices and all(analysis.POOL in k for k in choices)
    assert "(" not in choices[TOTAL]
    # Two files of one study give the same score twice, so it is not pooled.
    assert TOTAL.replace("+pilot_w1", "") not in views.variable_choices(
        result, [*FILES, "child_w2"]
    )
    groups = script.group_choices(result, FILES, {n: n for n in FILES})
    assert next(iter(groups)) == analysis.STUDY_KEY


def test_a_pooled_value_comes_from_each_persons_own_study(result, sample):
    pooled = analysis.values(result, sample, TOTAL)
    one = analysis.build_sample(result, ["child_w1"], True)
    alone = analysis.values(result, one, "example_mood.ems_total@child_w1")
    for study in ("mock_study", "pilot"):
        mine = pooled[[p.startswith(f"{study}/") for p in pooled.index]]
        assert mine.set_axis([p.split("/", 1)[1] for p in mine.index]).equals(alone)


def pooled_correlation(result, sample, rscript_path=None, method="pearson"):
    data = script.AnalysisData(result, sample)
    variables = [data.variable(TOTAL), data.variable(SADNESS)]
    code = script.correlation_code(variables, method, by_study=True)
    found, _ = script.run_code(result, sample, data.frame(), code, rscript_path)
    return script.read_correlations(found, [v.column for v in variables])[1][1][0]


def test_the_correlation_within_studies(result, sample):
    # The two studies hold the same answers, so within them r is one study's r on twice the n.
    one = analysis.build_sample(result, ["child_w1"], True)
    x = analysis.values(result, one, "example_mood.ems_total@child_w1")
    y = analysis.values(result, one, "example_mood.ems_sadness@child_w1")
    both = pd.concat([x, y], axis=1).dropna()
    r = stats.pearsonr(both.iloc[:, 0], both.iloc[:, 1]).statistic
    found = pooled_correlation(result, sample)
    assert (found.n, found.r) == (2 * len(both), pytest.approx(r))
    # One parameter more for the study than a plain correlation.
    df = found.n - 3
    t = r * (df / (1 - r**2)) ** 0.5
    assert found.p == pytest.approx(2 * stats.t.sf(abs(t), df))
    spearman = pooled_correlation(result, sample, method="spearman")
    assert spearman.r == pytest.approx(stats.spearmanr(both.iloc[:, 0], both.iloc[:, 1]).statistic)


def test_the_regression_with_the_study_as_a_fixed_effect(result, sample):
    data = script.AnalysisData(result, sample)
    x, y = data.variable(SADNESS), data.variable(TOTAL)
    found, _ = script.run_code(
        result, sample, data.frame(), script.regression_code([x], y, by_study=True), None
    )
    fit = script.read_regressions(found, {x.column: SADNESS})[SADNESS]
    one = analysis.build_sample(result, ["child_w1"], True)
    alone = analysis.regress(
        analysis.values(result, one, "example_mood.ems_sadness@child_w1"),
        analysis.values(result, one, "example_mood.ems_total@child_w1"),
    )
    assert (fit.slope, fit.intercept, fit.correlation.r) == pytest.approx(
        (alone.slope, alone.intercept, alone.correlation.r)
    )
    assert fit.correlation.n == 2 * alone.correlation.n and fit.correlation.low is None


def test_the_study_compares_as_a_group(result, sample):
    data = script.AnalysisData(result, sample)
    study, total = data.variable(analysis.STUDY_KEY), data.variable(TOTAL)
    frame = data.frame()
    assert [label for _, label in study.options] == ["Mock Family Study", "pilot"]
    plan = script.comparison_plan(frame, study, total)
    found, _ = script.run_code(result, sample, frame, plan.code, None)
    comparison = script.read_comparison(found, plan)
    # The same answers in both studies.
    assert comparison.statistic == pytest.approx(0) and comparison.effect == pytest.approx(0)


@needs_r
def test_r_and_python_agree_within_studies(result, sample):
    for method in ("pearson", "spearman"):
        python = pooled_correlation(result, sample, method=method)
        in_r = pooled_correlation(result, sample, rscript(), method=method)
        assert (in_r.n, in_r.r, in_r.p) == (
            python.n,
            pytest.approx(python.r),
            pytest.approx(python.p),
        )
    data = script.AnalysisData(result, sample)
    x, y = data.variable(SADNESS), data.variable(TOTAL)
    code = script.regression_code([x], y, by_study=True)
    fits = [
        script.read_regressions(
            script.run_code(result, sample, data.frame(), code, path)[0], {x.column: SADNESS}
        )[SADNESS]
        for path in (None, rscript())
    ]
    assert (fits[0].slope, fits[0].slope_se, fits[0].correlation.p) == pytest.approx(
        (fits[1].slope, fits[1].slope_se, fits[1].correlation.p)
    )
