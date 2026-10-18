import shutil
from glob import glob

import pytest

from labcatalog.pipeline import run_catalog
from labcatalog.reports import results
from labcatalog.stats import analysis, panel
from labcatalog.stats import analysis_script as script
from labcatalog.stats.rbridge import CFA_PACKAGES, r_status

X, Y = "example_parent_stress.eps_mean", "example_mood.ems_total"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


needs_lavaan = pytest.mark.skipif(
    rscript() is None or bool(r_status(rscript(), CFA_PACKAGES).missing),
    reason="R with lavaan is not installed",
)


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def model_of(result):
    waves = panel.common_waves(result, X, Y)
    datasets = list(dict.fromkeys([x for _, x, _ in waves] + [y for _, _, y in waves]))
    sample = analysis.build_sample(result, datasets, False)
    data = script.AnalysisData(result, sample)
    model = panel.PanelModel(
        "Stress",
        "Mood",
        [w for w, _, _ in waves],
        [data.variable(f"{X}@{x}") for _, x, _ in waves],
        [data.variable(f"{Y}@{y}") for _, _, y in waves],
    )
    return model, sample, data.frame()


def test_the_two_scores_meet_at_three_waves_of_one_study(result):
    assert X in panel.choices(result) and Y in panel.choices(result)
    assert panel.common_waves(result, X, Y) == [
        ("1", "parent_w1", "child_w1"),
        ("2", "parent_w2", "child_w2"),
        ("3", "parent_w3", "child_w3"),
    ]


def test_free_paths_get_a_label_each_and_equal_paths_share_one():
    free, equal = panel.syntax(3, True, False), panel.syntax(3, True, True)
    assert "wy3 ~ ay3*wy2 + cxy3*wx2" in free and "wy3 ~ ay*wy2 + cxy*wx2" in equal
    assert "RIx =~ 1*x1 + 1*x2 + 1*x3" in free and "RIx ~~ 0*wy1" in free
    clpm = panel.syntax(3, False, False)
    assert not any("RI" in line for line in clpm) and "wx2 ~ ax2*wx1 + cyx2*wy1" in clpm


def test_mplus_inputs_hold_the_three_models_and_their_data(result):
    model, _, frame = model_of(result)
    files = panel.mplus_files(model, frame, "Stress and Mood")
    assert set(files) == {panel.DATA, *(f"mplus_{m}.inp" for m in panel.MODELS)}
    assert "wy2 ON wx1;" in files["mplus_riclpm.inp"]
    assert "wy2 ON wx1 (cxy);" in files["mplus_riclpm_equal.inp"]
    assert "RIx" not in files["mplus_clpm.inp"]
    columns = [v.column for v in model.xs + model.ys]
    assert len(files[panel.DATA].splitlines()) == len(frame[columns].dropna(how="all"))


@needs_lavaan
def test_the_three_models_fit_and_compare(result):
    model, sample, frame = model_of(result)
    found, _ = script.run_code(result, sample, frame, panel.panel_code(model), rscript())
    fit = panel.read_fit(found)
    df = {name: values["df"] for name, values in fit.fits.items()}
    assert df[panel.EQUAL] - df[panel.RICLPM] == 4 and df[panel.CLPM] - df[panel.RICLPM] == 3
    assert fit.tests["equal"][1] == 4 and fit.tests["intercepts"][1] == 3
    for name in panel.MODELS:
        for kind in panel.LABELS:
            assert [p.wave for p in fit.lagged(name, kind)] == [2, 3]
    equal = fit.lagged(panel.EQUAL, "x_to_y")
    assert equal[0].estimate == pytest.approx(equal[1].estimate)
    assert fit.correlation(panel.RICLPM, "RIx", "RIy") is not None
    assert fit.correlation(panel.CLPM, "RIx", "RIy") is None
    text = results.panel_text(model, fit)
    assert text.startswith("A random intercept cross-lagged panel model (RI-CLPM) of Stress")
    assert "Within people, Stress predicted Mood at the next wave" in text
