import pytest

from labcatalog.config import FreedParameter
from labcatalog.exceptions import MplusError
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, group_invariance, invariance, mplus
from labcatalog.stats.cfa import SECOND_ORDER, SUBSCALE_SCORES, SUBSCALES, build_models


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
