import pytest

from labcatalog.config import FreedParameter
from labcatalog.exceptions import MplusError
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, group_invariance, invariance, mplus
from labcatalog.stats import analysis_script as script
from labcatalog.stats import mediation as med
from labcatalog.stats.cfa import SECOND_ORDER, SUBSCALE_SCORES, SUBSCALES, build_models
from labcatalog.stats.mplus_mediation import mediation_files


@pytest.fixture
def mood(mock_project):
    result = run_catalog(mock_project)
    models = build_models(result.project, result.catalog, result.datasets)
    return [m for m in models if (m.instrument_id, m.dataset) == ("example_mood", "child_w1")]


def test_each_model_gets_an_input_and_its_data(mood):
    files = mplus.cfa_files(mood, "wlsmv", "Example Mood Scale: EMS")
    assert len(files) == 2 * len(mood)
    kinds = [m.kind for m in mood]
    subscales = files[f"mplus_cfa_{kinds.index(SUBSCALES) + 1}.inp"]
    assert "  CATEGORICAL = x1-x9;" in subscales and "  ESTIMATOR = WLSMV;" in subscales
    assert "  f1 BY x1* x2 x3;" in subscales and "  f1 f2 f3@1;" in subscales
    assert "Example Mood Scale, EMS, child_w1" in subscales
    second = files[f"mplus_cfa_{kinds.index(SECOND_ORDER) + 1}.inp"]
    assert "  g BY f1* f2 f3;" in second and "  g@1;" in second
    n = kinds.index(SUBSCALE_SCORES) + 1
    scores = files[f"mplus_cfa_{n}.inp"]
    assert "CATEGORICAL" not in scores and "  ESTIMATOR = ML;" in scores
    assert "! x2 = ems_worry" in scores
    rows = files[f"mplus_cfa_{n}.dat"].splitlines()
    assert len(rows) == len(mood[kinds.index(SUBSCALE_SCORES)].data)
    assert all(len(row.split()) == 3 for row in rows)
    inputs = [text for name, text in files.items() if name.endswith(".inp")]
    assert all(len(line) <= 90 for text in inputs for line in text.splitlines())


def test_ml_items_are_continuous(mood):
    text = mplus.cfa_input(mood[0], "data.dat", "ml", "EMS")
    assert "CATEGORICAL" not in text and "  ESTIMATOR = ML;" in text


def test_mlr_is_written_as_mplus_mlr(mood):
    files = mplus.cfa_files(mood, "mlr", "EMS")
    assert all("  ESTIMATOR = MLR;" in t for n, t in files.items() if n.endswith(".inp"))
    assert not any("CATEGORICAL" in t for t in files.values())


def test_run_writes_an_output_beside_each_input(tmp_path):
    fake = tmp_path / "mplus.bat"
    fake.write_text("@copy %1 %2 >nul\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.inp").write_text("TITLE: a\n", encoding="utf-8")
    assert mplus.run(str(fake), work) == [work / "a.out"]
    with pytest.raises(MplusError, match="Mplus not found"):
        mplus.run(str(tmp_path / "missing.exe"), work)


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def wave_model(result):
    models = invariance.build_models(result.project, result.catalog, result.datasets)
    return next(m for m in models if m.instrument_id == "example_mood" and m.kind == SUBSCALES)


def test_waves_get_one_input_per_step_chained_by_difftest(result):
    model = wave_model(result)
    files = mplus.invariance_files(model, "wlsmv", "EMS")
    assert list(files) == [
        mplus.DATA,
        "mplus_invariance_1_configural.inp",
        "mplus_invariance_2_metric.inp",
        "mplus_invariance_3_scalar.inp",
    ]
    configural, metric, scalar = (files[n] for n in list(files)[1:])
    assert "  f1_t2 BY x1_t2*;" in configural and "  f1_t2@1;" in configural
    assert "  DIFFTEST = configural.dif;" in configural.split("SAVEDATA:")[1]
    assert "  f1_t2 BY x1_t2* (l1);" in metric and "  f1_t2*;" in metric
    assert "  DIFFTEST = configural.dif;" in metric.split("MODEL:")[0]
    assert "$" not in metric and "  [x1_t2$1] (t1_1);" in scalar and "  x1_t2*;" in scalar
    assert "  [f1_t2*];" in scalar and "SAVEDATA" not in scalar
    assert "  x1_t1 WITH x1_t3;" in configural
    rows = files[mplus.DATA].splitlines()
    assert all(len(row.split()) == 27 for row in rows) and "-999" in files[mplus.DATA]
    inputs = [text for name, text in files.items() if name.endswith(".inp")]
    assert all(len(line) <= 90 for text in inputs for line in text.splitlines())


def test_freed_parameters_stay_free_across_waves(result):
    model = wave_model(result)
    model.freed = [
        FreedParameter(instrument="example_mood", item="ems_2", parameter="loading"),
        FreedParameter(instrument="example_mood", item="ems_6", parameter="threshold"),
    ]
    files = mplus.invariance_files(model, "wlsmv", "EMS")
    scalar = files["mplus_invariance_3_scalar.inp"]
    assert "  f1_t2 BY x1_t2*;" in scalar and "(t2_1)" not in scalar
    assert "  x2_t2@1;" in scalar and "! Freed: ems_2 loading" in scalar
    ml = mplus.invariance_files(model, "ml", "EMS")["mplus_invariance_3_scalar.inp"]
    assert "CATEGORICAL" not in ml and "DIFFTEST" not in ml
    assert "  [x2_t2] (i2);" in ml and "$" not in ml


def test_groups_use_mplus_own_steps(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    gender = "item:example_demographics.dem_gender@parent_w1"
    [model] = group_invariance.group_models(result, sample, "example_mood@child_w1", gender)
    files = mplus.invariance_files(model, "wlsmv", "EMS")
    text = files["mplus_invariance.inp"]
    assert "  MODEL = CONFIGURAL METRIC SCALAR;" in text and "  f1 BY x1 x2 x3;" in text
    assert "  GROUPING = g (1 = g1 2 = g2);" in text and "! g1 = Girl" in text
    codes = {row.split()[-1] for row in files[mplus.DATA].splitlines()}
    assert codes == {"1", "2"}


def test_mlr_invariance_has_no_difftest(result):
    files = mplus.invariance_files(wave_model(result), "mlr", "EMS")
    metric = files["mplus_invariance_2_metric.inp"]
    assert "  ESTIMATOR = MLR;" in metric and "DIFFTEST" not in metric


def mediation_setup(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    data = script.AnalysisData(result, sample)
    keys = {
        "x": "example_parent_stress.eps_strain@parent_w1",
        "m": "example_child_sleep.ecs_total@parent_w1",
        "y": "example_mood.ems_total@child_w1",
        "w": "example_parent_stress.eps_child@parent_w1",
    }
    return data, keys


def test_score_mediation_centres_in_the_data_and_bootstraps_with_ml(result):
    data, keys = mediation_setup(result)
    x, m, y, w = (data.score(keys[r]) for r in "xmyw")
    model = med.MediationModel(x, m, y, moderators=[med.Moderator(w, ("b", "c"))], estimator="mlr")
    files = mediation_files(model, data.frame(), "EPS")
    text = files["mplus_mediation.inp"]
    assert "  ESTIMATOR = ML;" in text and "  BOOTSTRAP = 1000;" in text
    assert "Mplus bootstraps with ML only" in text
    assert "DEFINE:\n  xw = x*w;\n  mw = m*w;" in text
    assert "  y ON mw (b_mw);" in text and "  index = a*b_mw;" in text
    assert "  ind1 = a*(b + b_mw*(-" in text and "CINTERVAL(BOOTSTRAP)" in text
    rows = [list(map(float, r.split())) for r in files["mplus_mediation.dat"].splitlines()]
    assert all(len(r) == 4 for r in rows)
    # FIML keeps people who lack a value, and names the observed predictors' variances.
    seen = [r[0] for r in rows if r[0] != -999]
    assert len(seen) < len(rows) and abs(sum(seen) / len(seen)) < 1e-4
    assert "  x w xw mw;" in text
    assert all(len(line) <= 90 for line in text.splitlines())
    model.fiml = False
    complete = mediation_files(model, data.frame(), "EPS")
    assert "-999" not in complete["mplus_mediation.dat"]
    assert "  x w xw mw;" not in complete["mplus_mediation.inp"]


def test_item_mediation_uses_factors_and_xwith_for_latent_moderation(result):
    data, keys = mediation_setup(result)
    x, m, y, w = (data.score(keys[r], items=True) for r in "xmyw")
    plain = mediation_files(
        med.MediationModel(x, m, y, estimator="wlsmv", items=True), data.frame(), "EPS"
    )
    text = plain["mplus_mediation.inp"]
    assert "  X BY x_1-x_3;" in text and "CATEGORICAL" in text and "  BOOTSTRAP = 1000;" in text
    assert "  NEW(indirect total);" in text
    moderated = med.MediationModel(x, m, y, moderators=[med.Moderator(w, ("a",))], items=True)
    text = mediation_files(moderated, data.frame(), "EPS")["mplus_mediation.inp"]
    assert "  XW | X XWITH W;" in text and "  ALGORITHM = INTEGRATION;" in text
    assert "BOOTSTRAP" not in text.split("ANALYSIS:")[1] and "  W (v_w);" in text
    assert "  ind1 = (a + a_xw*(-SQRT(v_w)))*b;" in text
    assert all(len(line) <= 90 for line in text.splitlines())


def test_two_moderators_get_their_own_products_and_constraints(result):
    data, keys = mediation_setup(result)
    x, m, y, w = (data.score(keys[r]) for r in "xmyw")
    second = data.score("example_parent_stress.eps_strain@parent_w1")
    model = med.MediationModel(
        x, m, y, moderators=[med.Moderator(w, ("a",)), med.Moderator(second, ("a", "c"))]
    )
    text = mediation_files(model, data.frame(), "EPS")["mplus_mediation.inp"]
    assert "DEFINE:\n  xw1 = x*w1;\n  xw2 = x*w2;" in text
    assert "  m ON xw2 (a_xw2);" in text and "  y ON xw2 (c_xw2);" in text
    assert "  in11 = (a + a_xw1*(-" in text and "  di2_3 = c + c_xw2*(" in text
    assert "  index1 = a_xw1*b;" in text and "  index2 = a_xw2*b;" in text
    assert all(len(line) <= 90 for line in text.splitlines())
