import shutil
from glob import glob

import pytest

from labcatalog.gui import mediation as mediation_view
from labcatalog.pipeline import run_catalog
from labcatalog.reports import results
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats import mediation as med
from labcatalog.stats.mediation_r import mediation_code
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
    plain = mediation_code(model_of(data)).r
    assert '"m ~ a*x"' in plain and '"y ~ c*x + b*m"' in plain
    assert '"indirect := a*b"' in plain and '"total := c + a*b"' in plain
    assert "w_mean" not in plain
    first = mediation_code(model_of(data, ("a",))).r
    assert '"m ~ a*x + a_w*w + a_xw*xw"' in first and '"y ~ c*x + b*m"' in first
    assert 'at("indirect_%1$d := (a + a_xw*%2$s)*b")' in first and '"index := a_xw*b"' in first
    second = mediation_code(model_of(data, ("b", "c"))).r
    assert '"y ~ c*x + b*m + y_w*w + b_mw*mw + c_xw*xw"' in second
    assert 'at("direct_%1$d := c + c_xw*%2$s")' in second and '"index := a*b_mw"' in second
    both = mediation_code(model_of(data, ("a", "b"))).r
    assert "index" not in both
    direct = mediation_code(model_of(data, ("c",))).r
    assert '"indirect := a*b"' in direct and "indirect_" not in direct
    assert "ncpus = 4" in plain
    assert "parallel" not in mediation_code(model_of(data), workers=1).r


def test_covariates_enter_both_equations(setup):
    _, _, data = setup
    model = model_of(data, covariates=[data.score(CHILD)])
    code = mediation_code(model).r
    assert '"m ~ a*x + cov1"' in code and '"y ~ c*x + b*m + cov1"' in code


@needs_r
def test_mediation_runs_in_r_with_bootstrap_intervals(setup):
    result, sample, data = setup
    model = model_of(data, bootstrap=200)
    found, engine = script.run_code(
        result, sample, data.frame(), mediation_code(model, workers=1), rscript()
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
        code = mediation_code(model, workers=1)
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


@needs_r
def test_without_bootstrap_mlr_gives_wald_intervals_from_one_fit(setup):
    result, sample, data = setup
    model = model_of(data, ("a",), estimator=med.MLR, bootstrap=0)
    code = mediation_code(model)
    assert "bootstrap" not in code.r.split("model <- paste")[1] and 'estimator = "MLR"' in code.r
    found, _ = script.run_code(result, sample, data.frame(), code, rscript())
    fit = med.read_fit(found, model)
    assert fit.resamples == 0 and fit.fit["df"] == 2
    index = fit.effects["index"]
    # Wald intervals are symmetric around the estimate.
    assert index.estimate - index.low == pytest.approx(index.high - index.estimate)
    assert med.intervals_text(fit) == "Wald intervals, by the delta method for the defined effects"
    assert med.method_text(fit) == "robust maximum likelihood (MLR)"
    assert "Confidence intervals are Wald intervals" in results.mediation_text(model, fit)


STRAIN = "example_parent_stress.eps_strain@parent_w1"


def items_of(data, paths=(), latent_w=True, **options) -> med.MediationModel:
    w = data.score(CHILD, items=latent_w) if paths else None
    return med.MediationModel(
        data.score(STRAIN, items=True),
        data.score(SLEEP, items=True),
        data.score(MOOD, items=True),
        moderators=[med.Moderator(w, paths)] if paths else [],
        items=True,
        **options,
    )


def test_items_become_factors_and_moderation_goes_to_modsem(setup):
    _, _, data = setup
    wlsmv = mediation_code(items_of(data, estimator="wlsmv")).r
    assert '"X =~ x_1 + x_2 + x_3"' in wlsmv and '"M ~ a*X"' in wlsmv
    assert 'estimator = "DWLS", ordered = ordered' in wlsmv
    assert (
        'robust <- lavaan::sem(model, data = med, estimator = "WLSMV", ordered = ordered)' in wlsmv
    )
    latent = mediation_code(items_of(data, ("a",)))
    assert latent.packages == ("lavaan", "modsem")
    assert '"M ~ a*X + a_w*W + a_xw*X:W"' in latent.r and 'method = "lms"' in latent.r
    assert "first <- modsem::modsem(base" in latent.r
    observed = mediation_code(items_of(data, ("b",), latent_w=False)).r
    assert '"Y ~ c*X + b*M + y_w*w + b_mw*M:w"' in observed and 'method = "qml"' in observed
    assert "med$w <- med$w - w_mean" in observed


def test_items_mode_needs_items_of_their_own(setup):
    _, _, data = setup
    assert mediation_view.item_problem(items_of(data)) is None
    overlap = items_of(data)
    overlap.x = data.score(STRESS, items=True)
    overlap.moderators = [med.Moderator(data.score(CHILD, items=True), ("a",))]
    assert mediation_view.item_problem(overlap).startswith("X and W share items")
    overlap.x = data.score(STRAIN)
    assert mediation_view.item_problem(overlap) == (
        "In Items mode, X need a score with two or more items."
    )


@needs_r
def test_item_mediation_runs_in_lavaan_with_standardized_paths(setup):
    result, sample, data = setup
    model = items_of(data, bootstrap=0)
    found, _ = script.run_code(result, sample, data.frame(), mediation_code(model), rscript())
    fit = med.read_fit(found, model)
    e = fit.effects
    assert fit.package == med.LAVAAN and fit.fit["df"] > 0 and fit.resamples == 0
    assert e["indirect"].estimate == pytest.approx(e["a"].estimate * e["b"].estimate)
    assert e["indirect"].standardized == pytest.approx(e["a"].standardized * e["b"].standardized)
    text = results.mediation_text(model, fit)
    assert ", with each score as a factor of its items, was fitted in lavaan with" in text


@needs_r
def test_latent_moderation_runs_in_modsem_with_bootstrap(setup):
    result, sample, data = setup
    model = items_of(data, ("a",), bootstrap=10)
    code = mediation_code(model)
    found, _ = script.run_code(result, sample, data.frame(), code, rscript())
    fit = med.read_fit(found, model)
    e = fit.effects
    assert (fit.package, fit.method, fit.fit) == (med.MODSEM, "lms", {})
    assert fit.resamples <= 10 and fit.at[1] == 0 and fit.at[0] == pytest.approx(-fit.at[2])
    assert e["indirect_2"].estimate == pytest.approx(e["a"].estimate * e["b"].estimate)
    assert e["a"].standardized is not None and e["indirect_2"].standardized is None
    assert e["index"].low < e["index"].high
    _, rows = mediation_view.effects_table(model, fit)
    assert (
        rows[0]["beta"]
        and next(r for r in rows if r["effect"] == "Index of moderated mediation")["beta"] == ""
    )
    note = mediation_view.table_note(model, fit)
    assert "modsem, latent interactions by LMS with maximum likelihood" in note
    assert "A latent interaction model has no chi-square test of fit." in note
