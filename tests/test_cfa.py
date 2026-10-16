import shutil
import subprocess
from glob import glob

import pandas as pd
import pytest

from labcatalog.data.scoring import score_items
from labcatalog.exceptions import RError
from labcatalog.pipeline import run_catalog
from labcatalog.stats.cfa import ML, ONE_FACTOR, PYTHON, SUBSCALES, build_models, fit_models
from labcatalog.stats.rbridge import CFA_PACKAGES, r_status


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

    assert all(f.problem is None for f in fits.values())
    sleep = next(m for m in models if m.kind == SUBSCALES and m.dataset == "parent_w3")
    sleep.data = sleep.data.assign(**{sleep.data.columns[0]: 1.0})
    [broken] = fit_models([sleep], rscript())
    assert "only 1 level" in broken.problem
    assert broken.omega == {}


@needs_r
def test_three_items_give_omega_but_no_fit_indices(result):
    mood = next(m for m in models_of(result) if m.dataset == "child_w1" and m.kind == SUBSCALES)
    mood.kind, mood.factors = ONE_FACTOR, {"ems_sadness": mood.factors["ems_sadness"]}
    mood.data = mood.data[mood.factors["ems_sadness"]]
    [fit] = fit_models([mood], rscript())
    assert fit.fit == {"chisq": None, "df": 0.0}
    assert set(fit.omega) == {"ems_sadness"}


def test_models_fit_in_python_without_r(result):
    models = [m for m in models_of(result) if m.dataset == "child_w1"]
    fits = {(f.instrument_id, f.kind): f for f in fit_models(models, None)}
    mood = fits[("example_mood", SUBSCALES)]
    assert mood.engine == PYTHON and mood.problem is None
    assert mood.fit["df"] == 24 and mood.fit["srmr"] is None and mood.fit["cfi"] <= 1
    assert set(mood.omega) == {"ems_sadness", "ems_worry", "ems_low_positive"}
    assert len(mood.loadings) == 9 and all(0.5 < v < 1 for v in mood.loadings.values())
    sadness = next(m for m in models if m.kind == SUBSCALES and m.instrument_id == "example_mood")
    sadness.kind, sadness.factors = ONE_FACTOR, {"ems_sadness": sadness.factors["ems_sadness"]}
    sadness.data = sadness.data[sadness.factors["ems_sadness"]]
    [three] = fit_models([sadness], None)
    assert three.fit == {"chisq": None, "df": 0.0} and set(three.omega) == {"ems_sadness"}


ML_SCRIPT = """\
args <- commandArgs(trailingOnly = TRUE)
fit <- lavaan::cfa(readLines(args[2]), data = read.csv(args[1]), estimator = "ML", std.lv = TRUE)
measures <- lavaan::fitMeasures(fit, c("chisq", "df", "cfi", "tli", "rmsea"))
std <- lavaan::standardizedSolution(fit)
std <- std[std$op == "=~", ]
omega <- unlist(semTools::compRelSEM(fit))
write.csv(data.frame(name = c(names(measures), paste(std$lhs, std$rhs), names(omega)),
                     value = c(unname(measures), std$est.std, unname(omega))),
          args[3], row.names = FALSE)
"""


@needs_r
def test_with_ml_r_and_python_give_the_same_fit(result):
    models = [m for m in models_of(result) if m.dataset == "child_w1"]
    in_r = fit_models(models, rscript(), ML)
    in_python = fit_models(models, None, ML)
    for a, b in zip(in_r, in_python, strict=True):
        assert (a.engine, a.estimator, b.engine, b.estimator) == ("R", ML, PYTHON, ML)
        assert a.problem is None and b.problem is None
        for key in ("chisq", "df", "cfi", "tli", "rmsea"):
            if a.fit.get(key) is not None:
                assert a.fit[key] == pytest.approx(b.fit[key], abs=1e-3)
        assert a.loadings == pytest.approx(b.loadings, abs=1e-3)
        assert a.omega == pytest.approx(b.omega, abs=1e-3)
        assert a.fit.get("srmr") is not None or a.fit.get("df") == 0


@needs_r
def test_python_matches_lavaan_ml(result, tmp_path):
    mood = next(m for m in models_of(result) if m.dataset == "child_w1" and m.kind == SUBSCALES)
    [fit] = fit_models([mood], None)
    columns = list(mood.data.columns)
    mood.data.set_axis([f"x{i}" for i in range(1, 10)], axis=1).to_csv(
        tmp_path / "data.csv", index=False
    )
    syntax = "; ".join(
        f"f{i} =~ {' + '.join(f'x{columns.index(c) + 1}' for c in cols)}"
        for i, cols in enumerate(mood.factors.values(), start=1)
    )
    (tmp_path / "syntax.txt").write_text(syntax + "\n", encoding="utf-8")
    (tmp_path / "ml.R").write_text(ML_SCRIPT, encoding="utf-8")
    paths = [str(tmp_path / n) for n in ("ml.R", "data.csv", "syntax.txt", "out.csv")]
    subprocess.run([rscript(), *paths], check=True, capture_output=True)
    found = dict(pd.read_csv(tmp_path / "out.csv").itertuples(index=False))
    for key in ("chisq", "df", "tli", "rmsea"):
        assert fit.fit[key] == pytest.approx(found[key], abs=1e-3)
    assert fit.fit["cfi"] == pytest.approx(found["cfi"], abs=1e-3)
    scores = list(mood.factors)
    for (score, column), value in fit.loadings.items():
        name = f"f{scores.index(score) + 1} x{columns.index(column) + 1}"
        assert value == pytest.approx(found[name], abs=1e-3)
    for score, value in fit.omega.items():
        assert value == pytest.approx(found[f"f{scores.index(score) + 1}"], abs=1e-3)


@needs_r
def test_r_status_reports_the_version():
    status = r_status(rscript(), CFA_PACKAGES)
    assert status.version.startswith("R version")
    assert status.missing == []
