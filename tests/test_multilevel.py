import shutil
import subprocess
from glob import glob
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from labcatalog.pipeline import run_catalog
from labcatalog.stats import multilevel as ml
from labcatalog.stats.rbridge import MULTILEVEL_PACKAGES, r_status

EMS = "example_mood.ems_total"
CHILD = ["child_w1", "child_w2", "child_w3"]
GENDER = "item:example_demographics.dem_gender@parent_w1"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


def r_ready() -> bool:
    return rscript() is not None and not r_status(rscript(), MULTILEVEL_PACKAGES).missing


needs_r = pytest.mark.skipif(
    not r_ready(), reason="R with lme4, lmerTest and performance is not installed"
)


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def growth(**changes) -> ml.Model:
    return ml.Model(**({"outcome": EMS, "datasets": CHILD, "covariates": [GENDER]} | changes))


def nested() -> tuple[SimpleNamespace, ml.Model, ml.Long]:
    # Siblings within families, three waves each.
    rng = np.random.default_rng(3)
    rows = []
    for f in range(80):
        family = rng.normal(0, 1.0)
        for c in range(rng.integers(1, 4)):
            person, slope = rng.normal(0, 0.7), rng.normal(0, 0.2)
            for t in range(3):
                y = 10 + family + person + (0.3 + slope) * t + rng.normal(0, 0.5)
                rows.append({"id": f"{f}_{c}", "family": f"f{f}", "wave": t + 1, "time": t, "y": y})
    result = SimpleNamespace(
        project=SimpleNamespace(config=SimpleNamespace(project=SimpleNamespace(name="demo")))
    )
    model = ml.Model("x.y", ["a", "b", "c"], by_group=True)
    return result, model, ml.Long(pd.DataFrame(rows), "y", "family", [], 0)


def test_default_model_follows_a_total_score_over_waves(result):
    model = ml.default_model(result)
    assert len(model.datasets) == 3 and model.by_person and model.slope
    assert ml.occasions(result, EMS) == CHILD
    assert ml.problem(result, model) is None


def test_a_number_item_is_an_outcome_and_a_covariate(result):
    faa, motion = "item:eeg_resting.frontal_alpha_asymmetry", "item:fmri_resting.mean_fd@fmri_w1"
    assert faa in ml.outcome_choices(result)
    assert ml.occasions(result, faa) == ["eeg_w1", "eeg_w3"]
    assert motion in ml.covariate_choices(result, {n: n for n in result.datasets})
    model = ml.Model(faa, ["eeg_w1", "eeg_w3"], covariates=[motion], slope=False)
    long = ml.long_frame(result, model)
    assert long.outcome == "frontal_alpha_asymmetry"
    eeg = result.datasets["eeg_w3"].frame
    later = long.frame[long.frame["time"] == 1].set_index("id")[long.outcome]
    expected = pd.to_numeric(eeg["frontal_alpha_asymmetry"]).set_axis(eeg["pid"])
    pd.testing.assert_series_equal(
        later, expected.reindex(later.index), check_names=False, check_index_type=False
    )
    fitted = ml.run(result, model, long, "EEG frontal alpha asymmetry", None)
    assert len(fitted.fixed) == 3 and fitted.observations > 0


def test_problems_are_named(result):
    assert ml.problem(result, growth(datasets=["child_w1", "parent_w1"])) == (
        "Choose one dataset per wave."
    )
    assert ml.problem(result, growth(datasets=["child_w1"])).startswith("People need two")
    assert ml.problem(result, growth(by_person=False)) == (
        "Choose at least one level: people or groups."
    )
    assert ml.problem(result, growth(datasets=["child_w1"], by_person=False, by_group=True)) is None


def test_long_data_has_a_row_per_person_and_wave(result):
    long = ml.long_frame(result, growth())
    frame = long.frame
    assert list(frame.columns) == ["id", "wave", "time", "ems_total", "dem_gender_w1"]
    assert frame.groupby("wave")["time"].first().to_dict() == {"1": 0, "2": 1, "3": 2}
    assert len(frame) + long.left_out == sum(len(result.datasets[n].frame) for n in CHILD)
    # A parent's answer reaches the child through the family.
    parent = result.datasets["parent_w1"]
    family = parent.group[parent.frame[parent.id_column] == "1005P"].iloc[0]
    child = frame[(frame["id"].str.startswith("1005")) & (frame["time"] == 0)]
    assert child["dem_gender_w1"].iloc[0] == float(
        parent.frame.loc[parent.group == family, "dem_gender_w1"].iloc[0]
    )


def test_python_fit_reads_back_in_formula_order(result):
    model = growth()
    long = ml.long_frame(result, model)
    fitted = ml.run(result, model, long, "EMS Total score", None)
    assert fitted.engine == "Python"
    assert [t.label for t in fitted.fixed] == [
        "Intercept",
        "Time (waves since the first)",
        "EFB: What is your child's gender?: Boy",
        "EFB: What is your child's gender?: Another gender",
    ]
    assert [(v.level, v.term) for v in fitted.random] == [
        ("Person", "Intercept"),
        ("Person", "Time (waves since the first)"),
        ("Residual", ""),
    ]
    assert fitted.random[1].correlation is not None
    assert [level for level, _ in fitted.icc] == ["Person"] and 0 < fitted.icc[0][1] < 1
    assert fitted.observations + fitted.dropped == len(long.frame)
    assert all(t.df is None for t in fitted.fixed)
    assert ml.references(long) == [("EFB: What is your child's gender?", "Girl")]


def test_saved_python_script_runs_on_its_data(result, tmp_path):
    model = growth()
    long = ml.long_frame(result, model)
    long.frame.to_csv(tmp_path / ml.DATA_FILE, index=False)
    _, python = ml.scripts(result, model, long, "EMS Total score")
    (tmp_path / "multilevel.py").write_text(python, encoding="utf-8")
    done = subprocess.run(
        [shutil.which("python") or "python", "multilevel.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert "Mixed Linear Model Regression Results" in done.stdout


def test_groups_and_people_fit_in_python():
    result, model, long = nested()
    fitted = ml.run(result, model, long, "Y", None)
    assert [level for level, _ in fitted.icc] == ["Family", "Person"]
    assert [(v.level, v.term) for v in fitted.random] == [
        ("Family", "Intercept"),
        ("Person", "Intercept"),
        ("Person", "Time (waves since the first)"),
        ("Residual", ""),
    ]
    assert (fitted.people, fitted.groups) == (long.frame["id"].nunique(), 80)


def close(in_r: ml.Fitted, in_python: ml.Fitted) -> None:
    for a, b in zip(in_r.fixed, in_python.fixed, strict=True):
        assert a.label == b.label
        # The optimizers stop at slightly different points of a flat likelihood.
        assert abs(a.estimate - b.estimate) < 0.01 * a.se
        # statsmodels and lme4 get the fixed effects' covariance differently.
        assert a.se == pytest.approx(b.se, rel=0.05)
    for a, b in zip(in_r.random, in_python.random, strict=True):
        assert (a.level, a.term) == (b.level, b.term)
        assert a.variance == pytest.approx(b.variance, rel=1e-3, abs=1e-5)
    assert dict(in_r.icc) == pytest.approx(dict(in_python.icc), abs=1e-3)
    assert in_r.reml_criterion == pytest.approx(in_python.reml_criterion, rel=1e-6)
    assert (in_r.observations, in_r.people, in_r.groups) == (
        in_python.observations,
        in_python.people,
        in_python.groups,
    )


@needs_r
def test_r_and_python_agree_on_growth(result):
    model = growth()
    long = ml.long_frame(result, model)
    in_r = ml.run(result, model, long, "EMS Total score", rscript())
    assert in_r.engine == "R" and all(t.df is not None for t in in_r.fixed)
    assert in_r.aic is not None
    close(in_r, ml.run(result, model, long, "EMS Total score", None))


@needs_r
def test_r_and_python_agree_on_groups_and_people():
    result, model, long = nested()
    close(ml.run(result, model, long, "Y", rscript()), ml.run(result, model, long, "Y", None))
    one_wave = ml.Model("x.y", ["a"], by_person=False, by_group=True)
    first = ml.Long(
        long.frame[long.frame["time"] == 0].reset_index(drop=True), "y", "family", [], 0
    )
    close(
        ml.run(result, one_wave, first, "Y", rscript()), ml.run(result, one_wave, first, "Y", None)
    )
