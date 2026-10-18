import subprocess
from pathlib import Path

import pandas as pd
import pytest
from scipy import stats

from labcatalog.charts import views
from labcatalog.pipeline import run_catalog
from labcatalog.reports import results
from labcatalog.stats import (
    agreement,
    analysis,
    cfa,
    group_invariance,
    imputation,
    invariance,
    mplus,
)
from labcatalog.stats import analysis_script as script
from labcatalog.stats import measurement as mm
from labcatalog.stats import mediation as med
from labcatalog.stats.mediation_r import mediation_code
from tests.test_analysis_script import needs_r, rscript
from tests.test_imputation import needs_mice

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


WORRIES = "example_worries_temper.ewt_worries@child_w1+pilot_w1"
TEMPER = "example_worries_temper.ewt_temper@child_w1+pilot_w1"


def test_a_pooled_measurement_model_regresses_its_factors_on_the_study(result, sample):
    keys = [SADNESS, WORRIES, TEMPER]
    assert set(keys) <= set(mm.offered(result, {k: k for k in keys}))
    found = mm.plan(result, sample, keys)
    assert found.problem is None and found.covariates == {"study_2": "Study: pilot"}
    model = found.model
    assert model.covariates == ["study_2"] and model.dataset == "child_w1, pilot_w1"
    # Each study's people bring their own file's items, here the same answers twice.
    items = model.data.drop(columns="study_2")
    mine, theirs = items[model.data["study_2"] == 0], items[model.data["study_2"] == 1]
    assert len(mine) and mine.to_numpy().tolist() == theirs.to_numpy().tolist()
    texts = mm.script_files(model, cfa.WLSMV, found.labels | found.covariates, "t")
    assert "f1 + f2 + f3 ~ c1" in texts[mm.SCRIPT_FILE]
    assert "#   c1: Study: pilot" in texts[mm.SCRIPT_FILE]
    inp = mplus.cfa_input(model, "m.dat", cfa.WLSMV, "t")
    assert "f1 f2 f3 ON c1;" in inp and "f1 WITH f2;" in inp and "CATEGORICAL = x1-x11;" in inp


@needs_r
def test_the_same_answers_in_two_studies_give_one_studys_measurement_model(
    result, sample, tmp_path
):
    one = analysis.build_sample(result, ["child_w1"], True)
    alone_keys = [k.replace("+pilot_w1", "") for k in (SADNESS, WORRIES, TEMPER)]
    [alone] = cfa.fit_models([mm.plan(result, one, alone_keys).model], rscript(), cfa.ML)
    pooled = mm.plan(result, sample, [SADNESS, WORRIES, TEMPER])
    [fit] = cfa.fit_models([pooled.model], rscript(), cfa.ML)
    assert fit.problem is None and fit.n == 2 * alone.n
    first = {k: k.replace("+pilot_w1", "") for k in (SADNESS, WORRIES, TEMPER)}
    for (a, b), found in fit.correlations.items():
        same = alone.correlations.get((first[a], first[b]))
        assert found["r"] == pytest.approx(same["r"], abs=1e-4)
    assert list(fit.loadings.values()) == pytest.approx(list(alone.loadings.values()), abs=1e-4)
    # WLSMV keeps the study's column a number, not an ordered category.
    [ordinal] = cfa.fit_models([pooled.model], rscript(), cfa.WLSMV)
    assert ordinal.problem is None and ordinal.covariates == ["study_2"]
    assert "within studies" in results.cfa_text([ordinal], pooled.labels)
    # The R script beside the data gives the same fit and ω.
    texts = mm.script_files(pooled.model, cfa.WLSMV, pooled.labels | pooled.covariates, "t")
    for name, body in texts.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    with open(tmp_path / mm.SCRIPT_FILE, "a", encoding="utf-8") as f:
        f.write(
            'write.csv(t(lavaan::fitMeasures(fit, "chisq.scaled")), "fit.csv")\n'
            'write.csv(t(unlist(semTools::compRelSEM(alone))), "omega.csv")\n'
        )
    done = subprocess.run([rscript(), mm.SCRIPT_FILE], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert pd.read_csv(tmp_path / "fit.csv").iloc[0]["chisq.scaled"] == pytest.approx(
        ordinal.fit["chisq"], rel=1e-6
    )
    omega = pd.read_csv(tmp_path / "omega.csv").iloc[0]
    assert [omega[f"f{i}"] for i in (1, 2, 3)] == pytest.approx(list(ordinal.omega.values()))


def imputed(result, sample, keys, build, tmp_path):
    data = script.AnalysisData(result, sample)
    variables = [data.variable(k) for k in keys]
    plan = imputation.plan(data, keys, [], 5, 3)
    frame = data.frame()
    file = (tmp_path / imputation.file_name(frame, plan)).as_posix()
    found, _ = script.run_code(result, sample, frame, build(variables, plan, file), rscript())
    return plan, variables, found


def test_pooled_studies_are_imputed_each_by_itself(result, sample):
    data = script.AnalysisData(result, sample)
    plan = imputation.plan(data, [TOTAL, WORRIES], [], 5, 3)
    assert plan.by_study and len(plan.items) == 9 + 4
    assert plan.scores[0][1] == "sum"
    code = imputation.impute_r(plan, "kept.rds")
    assert "studies <- split(seq_len(nrow(d)), d$study)" in code
    one = analysis.build_sample(result, ["child_w1"], True)
    alone = imputation.plan(
        script.AnalysisData(result, one), [TOTAL.replace("+pilot_w1", "")], [], 5, 3
    )
    assert not alone.by_study and "studies <-" not in imputation.impute_r(alone, "kept.rds")


@needs_mice
def test_the_same_answers_imputed_in_two_studies_give_one_studys_correlations(
    result, sample, tmp_path
):
    keys = [TOTAL, WORRIES, TEMPER]
    plan, variables, found = imputed(
        result,
        sample,
        keys,
        lambda vs, plan, file: imputation.correlation_code(vs, "pearson", plan, file),
        tmp_path,
    )
    _, matrix = script.read_correlations(found, [v.column for v in variables])
    one = analysis.build_sample(result, ["child_w1"], True)
    alone_keys = [k.replace("+pilot_w1", "") for k in keys]
    _, alone_variables, alone_found = imputed(
        result,
        one,
        alone_keys,
        lambda vs, plan, file: imputation.correlation_code(vs, "pearson", plan, file),
        tmp_path,
    )
    _, alone = script.read_correlations(alone_found, [v.column for v in alone_variables])
    assert matrix[1][0].r == pytest.approx(alone[1][0].r, abs=1e-6)
    assert matrix[2][1].r == pytest.approx(alone[2][1].r, abs=1e-6)
    # Each study on its own has the one study's answers and imputations.
    pair = (variables[0].column, variables[1].column)
    each = script.read_study_correlations(found)
    assert sorted(each) == [1.0, 2.0]
    assert [each[k][pair].r for k in each] == pytest.approx([alone[1][0].r] * 2, abs=1e-6)
    data = script.AnalysisData(result, sample)
    plan = imputation.plan(data, keys, [], 5, 3)
    summary = imputation.summary_code(plan, (tmp_path / "s.rds").as_posix())
    found, _ = script.run_code(result, sample, data.frame(), summary, rscript())
    columns, _ = imputation.read_summary(found)
    assert {c.column for c in columns} == set(plan.columns)


@needs_mice
def test_a_pooled_regression_after_imputation_takes_the_study_as_fixed(result, sample, tmp_path):
    keys = [TOTAL, WORRIES]
    _, _, found = imputed(
        result,
        sample,
        keys,
        lambda vs, plan, file: imputation.regression_code(vs[1:], vs[0], plan, file),
        tmp_path,
    )
    one = analysis.build_sample(result, ["child_w1"], True)
    _, _, alone = imputed(
        result,
        one,
        [k.replace("+pilot_w1", "") for k in keys],
        lambda vs, plan, file: imputation.regression_code(vs[1:], vs[0], plan, file),
        tmp_path,
    )
    pooled_row, alone_row = found["regressions"].iloc[0], alone["regressions"].iloc[0]
    assert pooled_row["n"] == 2 * alone_row["n"]
    for column in ("slope", "intercept", "r"):
        assert pooled_row[column] == pytest.approx(alone_row[column], abs=1e-6)


def test_mediation_of_factors_takes_the_study_as_fixed(result, sample):
    data = script.AnalysisData(result, sample)
    model = item_mediation(data, "child_w1+pilot_w1")
    model.covariates = data.study_dummies()
    code = mediation_code(model, workers=1)
    assert '"M ~ a*X + cov1"' in code.r and "cov1 = d[[" in code.r
    if not rscript():
        return
    fit = med.read_fit(script.run_code(result, sample, data.frame(), code, rscript())[0], model)
    one = analysis.build_sample(result, ["child_w1"], True)
    alone_data = script.AnalysisData(result, one)
    alone_model = item_mediation(alone_data, "child_w1")
    found, _ = script.run_code(
        result, one, alone_data.frame(), mediation_code(alone_model, workers=1), rscript()
    )
    alone = med.read_fit(found, alone_model)
    assert fit.n == 2 * alone.n
    for path in ("a", "b", "c", "indirect"):
        assert fit.effects[path].estimate == pytest.approx(alone.effects[path].estimate, abs=1e-4)


def item_mediation(data, files: str) -> med.MediationModel:
    x, m, y = (
        data.score(f"{key}@{files}", items=True)
        for key in (
            "example_mood.ems_sadness",
            "example_worries_temper.ewt_worries",
            "example_worries_temper.ewt_temper",
        )
    )
    return med.MediationModel(x, m, y, items=True, bootstrap=0)


@needs_r
def test_a_moderated_mediation_of_factors_fits_with_the_study(result, sample):
    data = script.AnalysisData(result, sample)
    model = item_mediation(data, "child_w1+pilot_w1")
    w = data.score("example_mood.ems_low_positive@child_w1+pilot_w1")
    model.moderators = [med.Moderator(w, ("b",))]
    model.covariates = data.study_dummies()
    code = mediation_code(model, workers=1)
    assert "modsem" in code.packages and "cov1" in code.r
    found, _ = script.run_code(result, sample, data.frame(), code, rscript())
    fit = med.read_fit(found, model)
    assert fit.package == med.MODSEM and fit.n > len(sample.people) / 2
    assert all(fit.effects[k].estimate == fit.effects[k].estimate for k in ("a", "b", "b_mw"))


def test_pooled_labels_lose_the_whole_dataset_label(result):
    labels = {n: f"{n} (Wave 1, child)" for n in FILES}
    choices = script.group_choices(result, FILES, labels)
    assert all("(" not in text for text in choices.values())
    assert analysis.without_suffix("EMS (total) (child_w1 (Wave 1, child))") == "EMS (total)"


@pytest.fixture
def raters(pilot_project: Path):
    # The pilot also copies the parents' ratings of the child, so both studies have two raters.
    config = pilot_project / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8").replace("correlate_by: family", "correlate_by: id")
    text = text.replace(
        "datasets:\n",
        "datasets:\n  - {name: pilot_parent, modality: questionnaire, study: pilot, wave: 1, "
        "reporter: parent, source: csv, path: data/parent_child_w1.csv, "
        "respondent_column: parent_pid, map: parent_child_w1}\n",
        1,
    )
    config.write_text(text, encoding="utf-8")
    study = pilot_project / "studies" / "pilot.yaml"
    study.write_text(
        study.read_text(encoding="utf-8")
        + "  - {instrument: example_worries_temper, datasets: [pilot_parent], target: child}\n",
        encoding="utf-8",
    )
    return run_catalog(pilot_project)


AGREEMENT_FILES = ["child_w1", "parent_child_w1", "pilot_w1", "pilot_parent"]


@needs_r
def test_agreement_of_two_studies_with_the_same_ratings_is_one_studys(raters):
    pooled = analysis.build_sample(raters, AGREEMENT_FILES, True)
    one = analysis.build_sample(raters, AGREEMENT_FILES[:2], True)
    labels = {n: n for n in AGREEMENT_FILES}
    items = [k for k in agreement.choices(raters, AGREEMENT_FILES, labels) if ".ewt_1@" in k]
    assert items == [
        "item:example_worries_temper.ewt_1@child_w1+pilot_w1",
        "item:example_worries_temper.ewt_1@parent_child_w1+pilot_parent",
    ]
    totals = [
        "example_worries_temper.ewt_total@child_w1+pilot_w1",
        "example_worries_temper.ewt_total@parent_child_w1+pilot_parent",
    ]
    for keys in (items, totals):
        found = {}
        for name, sample, used in (
            ("pooled", pooled, keys),
            ("one", one, [first(k) for k in keys]),
        ):
            data = script.AnalysisData(raters, sample)
            variables = [data.variable(k) for k in used]
            code = agreement.agreement_code(variables, name == "pooled")
            outputs, _ = script.run_code(raters, sample, data.frame(), code, rscript())
            found[name] = agreement.read_agreement(outputs, variables)
        pooled_fit, alone = found["pooled"], found["one"]
        if pooled_fit.kind == agreement.KAPPA:
            assert pooled_fit.kappas[0].kappa == pytest.approx(alone.kappas[0].kappa)
            assert pooled_fit.kappas[0].n == 2 * alone.kappas[0].n
            each = [pairs[0].kappa for pairs in pooled_fit.study_kappas.values()]
            assert each == pytest.approx([alone.kappas[0].kappa] * 2)
        else:
            # Each person twice changes the mean squares' df a little, so close, not equal.
            assert pooled_fit.icc[1].icc == pytest.approx(alone.icc[1].icc, abs=0.005)
            assert pooled_fit.n == 2 * alone.n
            each = [rows[1].icc for rows in pooled_fit.study_icc.values()]
            assert each == pytest.approx([alone.icc[1].icc] * 2, abs=1e-6)
            studies = {1.0: "Mock Family Study", 2.0: "pilot"}
            text = results.agreement_text(pooled_fit, studies=studies)
            assert "In each study on its own, ICC(2,1) was" in text and "in pilot" in text


def first(key: str) -> str:
    return analysis.first_key(key)


def test_two_reporters_of_one_score_pool_apart(raters):
    choices = views.variable_choices(raters, AGREEMENT_FILES)
    child = choices["example_worries_temper.ewt_total@child_w1+pilot_w1"]
    parent = choices["example_worries_temper.ewt_total@parent_child_w1+pilot_parent"]
    assert child.endswith("(child)") and parent.endswith("(parent)")
    assert choices["example_mood.ems_total@child_w1+pilot_w1"] == "EMS total score"
