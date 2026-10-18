import shutil
import subprocess
from glob import glob

import pandas as pd
import pytest

from labcatalog.pipeline import run_catalog
from labcatalog.reports import results
from labcatalog.stats import analysis, cfa, mplus
from labcatalog.stats import measurement as mm
from labcatalog.stats.analysis import CHOICE
from labcatalog.stats.rbridge import CFA_PACKAGES, r_status

EMS = "example_mood.ems_total@child_w1"
SADNESS = "example_mood.ems_sadness@child_w1"
EPS = "example_parent_stress.eps_mean@parent_w1"
ECS = "example_child_sleep.ecs_total@parent_w1"


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


@pytest.fixture
def sample(result):
    return analysis.build_sample(result, ["parent_w1", "child_w1"], True)


def test_factors_need_items_of_their_own_and_a_second_factor(result, sample):
    assert "share items" in mm.plan(result, sample, [EMS, SADNESS]).problem
    assert "two or more" in mm.plan(result, sample, [EMS]).problem
    found = mm.plan(result, sample, [EMS, EPS])
    assert found.problem is None and found.ordinal
    assert list(found.model.factors) == [EMS, EPS]
    assert not found.model.data.isna().any().any()


def test_wlsmv_needs_every_item_to_have_answer_options(result):
    assert mm.ordinal(result, [EMS, EPS])
    score = next(s for s in result.catalog.scores if s.key == EMS)
    item = next(
        v
        for v in result.catalog.variables_for(score.dataset)
        if v.column == score.columns[0] and v.type == CHOICE
    )
    item.type = "number"
    assert not mm.ordinal(result, [EMS, EPS])


@needs_r
def test_the_factors_of_several_instruments_correlate_and_the_script_fits_the_same(
    result, sample, tmp_path
):
    found = mm.plan(result, sample, [EMS, EPS, ECS])
    [fit] = cfa.fit_models([found.model], rscript(), cfa.WLSMV)
    assert fit.problem is None
    assert len(fit.correlations) == 3
    for r in fit.correlations.values():
        assert r["low"] < r["r"] < r["high"] and 0 <= r["p"] <= 1
    assert set(fit.omega) == {EMS, EPS, ECS}
    text = results.cfa_text([fit], found.labels)
    assert text.startswith("A measurement model with a correlated factor for each of")
    assert "Factor correlations ranged from" in text
    files = mm.script_files(found.model, cfa.WLSMV, found.labels, "test")
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    with open(tmp_path / mm.SCRIPT_FILE, "a", encoding="utf-8") as f:
        f.write(
            'write.csv(t(lavaan::fitMeasures(fit, c("chisq.scaled", "df.scaled"))), "fit.csv")\n'
        )
    done = subprocess.run([rscript(), mm.SCRIPT_FILE], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    saved = pd.read_csv(tmp_path / "fit.csv").iloc[0]
    assert saved["chisq.scaled"] == pytest.approx(fit.fit["chisq"], rel=1e-6)
    assert saved["df.scaled"] == pytest.approx(fit.fit["df"])
    inputs = mplus.cfa_files([found.model], cfa.WLSMV, "test")
    assert any(name.endswith(".inp") for name in inputs)
