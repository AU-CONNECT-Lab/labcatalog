import shutil
from glob import glob

import pytest

from labcatalog.cfa import ONE_FACTOR, SUBSCALES, build_models, fit_models
from labcatalog.exceptions import RError
from labcatalog.pipeline import run_catalog
from labcatalog.rbridge import CFA_PACKAGES, r_status
from labcatalog.scoring import score_items


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


def r_ready() -> bool:
    return rscript() is not None and not r_status(rscript(), CFA_PACKAGES).missing


needs_r = pytest.mark.skipif(not r_ready(), reason="R with lavaan and semTools is not installed")


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def models_of(result):
    return build_models(result.project, result.catalog, result.datasets)


def test_subscales_share_a_model_and_the_total_gets_its_own(result):
    found = {(m.instrument_id, m.dataset, m.kind): m for m in models_of(result)}
    mood = found[("example_mood", "child_w1", SUBSCALES)]
    assert list(mood.factors) == ["ems_sadness", "ems_worry", "ems_low_positive"]
    total = found[("example_mood", "child_w1", ONE_FACTOR)]
    assert list(total.factors) == ["ems_total"]
    assert len(total.data.columns) == 9
    assert not any(m.instrument_id == "example_screen_time" for m in found.values())


def test_model_data_are_the_reversed_items_of_people_who_answered_all(result):
    model = next(
        m
        for m in models_of(result)
        if m.dataset == "parent_w1" and m.kind == ONE_FACTOR and "eps_mean" in m.factors
    )
    score = next(
        s for s in result.catalog.scores if s.key == "example_parent_stress.eps_mean@parent_w1"
    )
    expected = score_items(result.datasets["parent_w1"], score).dropna()
    assert model.data.equals(expected)
    raw = result.datasets["parent_w1"].numbers("eps_2_w1")[model.data.index]
    assert (model.data["eps_2_w1"] + raw == 6).all()


def test_a_wrong_rscript_path_is_explained(result):
    with pytest.raises(RError, match="Rscript not found"):
        fit_models(models_of(result)[:1], "C:/no/such/Rscript.exe")


@needs_r
def test_models_fit_in_r_with_omega_for_every_score(result):
    models = [m for m in models_of(result) if m.dataset in ("child_w1", "parent_w3")]
    fits = {(f.instrument_id, f.dataset, f.kind): f for f in fit_models(models, rscript())}

    mood = fits[("example_mood", "child_w1", SUBSCALES)]
    assert mood.problem is None
    assert mood.n == len(
        next(m for m in models if m.kind == SUBSCALES and m.dataset == "child_w1").data
    )
    assert mood.fit["df"] == 24
    assert set(mood.fit) == {"chisq", "df", "p", "cfi", "tli", "rmsea", "srmr"}
    assert set(mood.omega) == {"ems_sadness", "ems_worry", "ems_low_positive"}
    assert all(0.5 < v < 1 for v in mood.omega.values())
    assert len(mood.loadings) == 9 and all(v > 0.5 for v in mood.loadings.values())
    assert set(fits[("example_mood", "child_w1", ONE_FACTOR)].omega) == {"ems_total"}

    sleep = fits[("example_child_sleep", "parent_w3", SUBSCALES)]
    assert sleep.problem.startswith("improper solution")
    assert sleep.omega == {}


@needs_r
def test_three_items_give_omega_but_no_fit_indices(result):
    mood = next(m for m in models_of(result) if m.dataset == "child_w1" and m.kind == SUBSCALES)
    mood.kind, mood.factors = ONE_FACTOR, {"ems_sadness": mood.factors["ems_sadness"]}
    mood.data = mood.data[mood.factors["ems_sadness"]]
    [fit] = fit_models([mood], rscript())
    assert fit.fit == {"chisq": None, "df": 0.0}
    assert set(fit.omega) == {"ems_sadness"}


@needs_r
def test_r_status_reports_the_version():
    status = r_status(rscript(), CFA_PACKAGES)
    assert status.version.startswith("R version")
    assert status.missing == []
