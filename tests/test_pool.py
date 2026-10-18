from pathlib import Path

import pandas as pd
import pytest
from scipy import stats

from labcatalog.charts import views
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, group_invariance, invariance
from labcatalog.stats import analysis_script as script
from labcatalog.stats import mediation as med
from labcatalog.stats.mediation_r import mediation_code
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


def test_each_study_has_its_own_correlations_too(result, sample):
    one = analysis.build_sample(result, ["child_w1"], True)
    x = analysis.values(result, one, "example_mood.ems_total@child_w1")
    y = analysis.values(result, one, "example_mood.ems_sadness@child_w1")
    alone = analysis.correlate(x, y)
    data = script.AnalysisData(result, sample)
    variables = [data.variable(TOTAL), data.variable(SADNESS)]
    code = script.correlation_code(variables, "pearson", by_study=True)
    pair = tuple(v.column for v in variables)
    paths = [None, rscript()] if rscript() else [None]
    for path in paths:
        found, _ = script.run_code(result, sample, data.frame(), code, path)
        each = script.read_study_correlations(found)
        assert sorted(each) == [1.0, 2.0]
        for study in each.values():
            assert (study[pair].n, study[pair].r, study[pair].p) == (
                alone.n,
                pytest.approx(alone.r),
                pytest.approx(alone.p),
            )


MOOD = "example_mood@child_w1+pilot_w1"


def test_an_instrument_is_tested_across_studies(result, sample):
    choices = group_invariance.measure_choices(
        result, FILES, ["example_mood"], {n: n for n in FILES}
    )
    assert MOOD in choices and "(" not in choices[MOOD]
    [model] = group_invariance.group_models(result, sample, MOOD, analysis.STUDY_KEY)
    assert model.across == analysis.STUDY_KEY
    assert list(model.occasions) == ["Mock Family Study", "pilot"]
    mine, theirs = model.occasions.values()
    # Each study's group holds its own people's answers, the same answers in both.
    assert all(p.startswith("mock_study/") for p in mine.index)
    assert mine.to_numpy().tolist() == theirs.to_numpy().tolist()


@needs_r
def test_the_same_answers_in_two_studies_hold_every_step(result, sample):
    [model] = group_invariance.group_models(result, sample, MOOD, analysis.STUDY_KEY)
    [test] = invariance.fit_models([model], rscript(), "ml")
    assert test.problem is None and [s.step for s in test.steps] == [
        "configural",
        "metric",
        "scalar",
    ]
    chisq = [s.fit["chisq"] for s in test.steps]
    assert chisq == pytest.approx([chisq[0]] * 3, abs=1e-4)
    assert test.steps[2].fit["df"] > test.steps[1].fit["df"] > test.steps[0].fit["df"]


def test_mediation_takes_the_study_as_fixed(result, sample):
    data = script.AnalysisData(result, sample)
    [pilot] = data.study_dummies()
    assert (pilot.label, data.frame()[pilot.column].sum()) == (
        "Study: pilot",
        len(sample.people) / 2,
    )
    model = mediation_model(data, "child_w1+pilot_w1")
    model.covariates = data.study_dummies()
    code = mediation_code(model, workers=1)
    assert '"m ~ a*x + cov1"' in code.r and '"y ~ c*x + b*m + cov1"' in code.r
    if not rscript():
        return
    fit = med.read_fit(script.run_code(result, sample, data.frame(), code, rscript())[0], model)
    one = analysis.build_sample(result, ["child_w1"], True)
    alone_data = script.AnalysisData(result, one)
    alone_model = mediation_model(alone_data, "child_w1")
    code = mediation_code(alone_model, workers=1)
    found, _ = script.run_code(result, one, alone_data.frame(), code, rscript())
    alone = med.read_fit(found, alone_model)
    # The same answers in both studies: the same paths on twice the people.
    assert fit.n == 2 * alone.n
    for path in ("a", "b", "c", "indirect"):
        assert fit.effects[path].estimate == pytest.approx(alone.effects[path].estimate)


def mediation_model(data, files: str) -> med.MediationModel:
    x, m, y = (
        data.score(f"{key}@{files}")
        for key in (
            "example_mood.ems_total",
            "example_worries_temper.ewt_worries",
            "example_worries_temper.ewt_temper",
        )
    )
    return med.MediationModel(x, m, y)


def test_the_example_pools_its_two_studies(example_project):
    result = run_catalog(example_project)
    assert list(result.project.config.studies) == ["mock_study", "mock_study_2"]
    # The second study adds no errors of its own.
    assert not [
        i for i in result.report.issues if i.level == "error" and "s2_" in (i.location or "")
    ]
    files = ["parent_w1", "s2_parent_baseline"]
    choices = views.variable_choices(result, files)
    assert "example_child_sleep.ecs_total@parent_w1+s2_parent_baseline" in choices
    # 1001P of each study is someone else, with a parent of their own family.
    people = analysis.build_sample(result, files, True).people
    assert {"mock_study/1001", "mock_study_2/1001"} <= set(people)
