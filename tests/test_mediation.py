import shutil
from glob import glob

import pytest

from labcatalog.gui import mediation as mediation_view
from labcatalog.pipeline import run_catalog
from labcatalog.reports import results
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats import mediation as med
from labcatalog.stats.rbridge import r_status

STRESS = "example_parent_stress.eps_mean@parent_w1"
SLEEP = "example_child_sleep.ecs_total@parent_w1"
MOOD = "example_mood.ems_total@child_w1"
CHILD = "example_parent_stress.eps_child@parent_w1"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


needs_r = pytest.mark.skipif(
    rscript() is None or bool(r_status(rscript(), ("lavaan",)).missing),
    reason="R with lavaan is not installed",
)


@pytest.fixture
def setup(mock_project):
    result = run_catalog(mock_project)
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    return result, sample, script.AnalysisData(result, sample)


def model_of(data, paths=(), **options) -> med.MediationModel:
    moderators = [med.Moderator(data.score(CHILD), paths)] if paths else []
    return med.MediationModel(
        data.score(STRESS), data.score(SLEEP), data.score(MOOD), moderators=moderators, **options
    )


def test_each_moderated_path_adds_its_terms_and_effects(setup):
    _, _, data = setup
    plain = med.mediation_code(model_of(data)).r
    assert '"m ~ a*x"' in plain and '"y ~ c*x + b*m"' in plain
    assert '"indirect := a*b"' in plain and '"total := c + a*b"' in plain
    assert "w_mean" not in plain
    first = med.mediation_code(model_of(data, ("a",))).r
    assert '"m ~ a*x + a_w*w + a_xw*xw"' in first and '"y ~ c*x + b*m"' in first
    assert 'at("indirect_%1$d := (a + a_xw*%2$s)*b")' in first and '"index := a_xw*b"' in first
    second = med.mediation_code(model_of(data, ("b", "c"))).r
    assert '"y ~ c*x + b*m + y_w*w + b_mw*mw + c_xw*xw"' in second
    assert 'at("direct_%1$d := c + c_xw*%2$s")' in second and '"index := a*b_mw"' in second
    both = med.mediation_code(model_of(data, ("a", "b"))).r
    assert "index" not in both
    direct = med.mediation_code(model_of(data, ("c",))).r
    assert '"indirect := a*b"' in direct and "indirect_" not in direct
    assert "ncpus = 4" in plain
    assert "parallel" not in med.mediation_code(model_of(data), workers=1).r


def test_covariates_enter_both_equations(setup):
    _, _, data = setup
    model = model_of(data, covariates=[data.score(CHILD)])
    code = med.mediation_code(model).r
    assert '"m ~ a*x + cov1"' in code and '"y ~ c*x + b*m + cov1"' in code


@needs_r
def test_mediation_runs_in_r_with_bootstrap_intervals(setup):
    result, sample, data = setup
    model = model_of(data, bootstrap=200)
    found, engine = script.run_code(
        result, sample, data.frame(), med.mediation_code(model, workers=1), rscript()
    )
    fit = med.read_fit(found, model)
    e = fit.effects
    assert engine == script.R and fit.resamples <= 200 and fit.n > 100
    assert e["indirect"].estimate == pytest.approx(e["a"].estimate * e["b"].estimate)
    assert e["total"].estimate == pytest.approx(e["c"].estimate + e["indirect"].estimate)
    assert all(v.low < v.estimate < v.high for v in e.values())
    assert fit.fit["df"] == 0 and fit.at == []


@needs_r
def test_mlr_keeps_the_estimates_and_gives_robust_fit(setup):
    result, sample, data = setup
    fits = {}
    for estimator in (med.ML, med.MLR):
        model = model_of(data, ("a",), estimator=estimator, bootstrap=200)
        code = med.mediation_code(model, workers=1)
        found, _ = script.run_code(result, sample, data.frame(), code, rscript())
        fits[estimator] = med.read_fit(found, model)
    ml, mlr = fits[med.ML], fits[med.MLR]
    assert {k: v.estimate for k, v in ml.effects.items()} == pytest.approx(
        {k: v.estimate for k, v in mlr.effects.items()}
    )
    assert ml.effects["index"].low == pytest.approx(mlr.effects["index"].low)
    assert ml.fit["df"] == mlr.fit["df"] == 2
    assert ml.fit["chisq"] != pytest.approx(mlr.fit["chisq"])
    # Conditional effects at the moderator's mean and 1 SD either side.
    assert len(ml.at) == 3 and ml.at[0] < ml.at[1] < ml.at[2]
    assert {"indirect_1", "indirect_2", "indirect_3"} <= set(ml.effects)
    assert ml.effects["indirect_2"].estimate == pytest.approx(
        ml.effects["a"].estimate * ml.effects["b"].estimate
    )


def effect(estimate: float, low: float = -1.0, high: float = 1.0) -> med.Effect:
    return med.Effect("", estimate, 0.1, 0.04, low, high)


def test_the_paragraph_gives_paths_and_effects_with_their_intervals(setup):
    _, _, data = setup
    model = model_of(data)
    fit = med.MediationFit(
        150,
        {
            "a": effect(1.47, 0.81, 2.0),
            "b": effect(0.53),
            "c": effect(3.05),
            "indirect": effect(0.78, 0.35, 1.28),
            "total": effect(3.83),
        },
        {"df": 0.0},
        resamples=998,
    )
    text = results.mediation_text(model, fit)
    assert text.startswith(
        "A mediation model of EPS Mean score on EMS Total score through ECS Total score was "
        "fitted in lavaan with maximum likelihood (N = 150). The path from EPS Mean score to ECS "
        "Total score was a = 1.47, 95% CI [0.81, 2.00]"
    )
    assert "The indirect effect through ECS Total score was ab = 0.78, 95% CI [0.35, 1.28]" in text
    assert text.endswith("percentile bootstrap intervals from 998 of 1000 resamples.")
    moderated = model_of(data, ("a",))
    fit.effects |= {
        "a_xw": effect(0.38),
        "index": effect(0.2),
        **{f"indirect_{k}": effect(0.1 * k) for k in (1, 2, 3)},
    }
    del fit.effects["indirect"], fit.effects["total"]
    fit.at, fit.fit = [1.9, 2.9, 3.8], {"chisq": 1.08, "df": 2.0, "pvalue": 0.58, "cfi": 1.0}
    text = results.mediation_text(moderated, fit)
    assert "a = 1.47, 95% CI [0.81, 2.00] at the mean of the moderator" in text
    assert "The interaction was EPS Mean score × EPS Child-related on ECS Total score" in text
    assert "The conditional indirect effect was 0.10, 95% CI [-1.00, 1.00] at 1 SD below" in text
    assert "The index of moderated mediation was 0.20" in text
    assert "The model gave χ²(2) = 1.08, p = .580, CFI = 1.00." in text


def test_the_table_names_each_effect_and_the_diagram_draws_the_moderator(setup):
    _, _, data = setup
    model = model_of(data, ("a", "c"))
    fit = med.MediationFit(
        150,
        {
            "a": effect(1.0),
            "c": effect(2.0),
            "indirect_1": effect(0.3),
            "direct_1": effect(2.1, None, None),
        },
        {"df": 0.0},
        at=[1.9, 2.9, 3.8],
    )
    _, rows = mediation_view.effects_table(model, fit)
    names = [r["effect"] for r in rows]
    assert names == [
        "a: X → M",
        "c′: X → Y at the mean of W",
        "Indirect at W = 1 SD below the mean",
        "Direct at W = 1 SD below the mean",
    ]
    assert rows[-1]["ci"] == ""
    svg = mediation_view.diagram(model, fit)
    assert svg.count("stroke-dasharray") == 2 and "a = 1.00" in svg and "c′ = 2.00" in svg
    assert mediation_view.diagram(model_of(data), None).count("stroke-dasharray") == 0
