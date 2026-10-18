import shutil
from glob import glob

import pytest

from labcatalog.gui import panel as panel_view
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


@pytest.fixture
def two(mock_project):
    # A copy of the study as a second one: the same files, so each group gives the same model.
    root = mock_project
    shutil.copy(root / "maps" / "roster_mock_study.csv", root / "maps" / "roster_copy.csv")
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8").replace(
        "\n# One entry per data file",
        "  copy:\n    waves: {1: {}, 2: {}, 3: {}}\n    roster: {path: data/participants.csv, "
        "id_column: pid, group_column: family_id, role_column: role, "
        "instrument: example_participants}\n\n# One entry per data file",
    )
    copies = "".join(
        f"  - {{name: copy_{who}_w{i}, modality: questionnaire, study: copy, wave: {i}, "
        f"reporter: {who}, source: csv, path: data/{who}_w{i}.csv, map: {who}_w{i}}}\n"
        for i in (1, 2, 3)
        for who in ("parent", "child")
    )
    config.write_text(text.replace("datasets:\n", f"datasets:\n{copies}", 1), encoding="utf-8")
    # Every instrument the copied maps describe, so the copy is as valid as the study.
    parents = ", ".join(f"copy_parent_w{i}" for i in (1, 2, 3))
    children = ", ".join(f"copy_child_w{i}" for i in (1, 2, 3))
    (root / "studies" / "copy.yaml").write_text(
        "study: copy\nadministrations:\n"
        f"  - {{instrument: example_parent_stress, datasets: [{parents}], target: self}}\n"
        f"  - {{instrument: example_child_sleep, datasets: [{parents}], target: child}}\n"
        f"  - {{instrument: example_demographics, datasets: [{parents}]}}\n"
        f"  - {{instrument: example_mood, datasets: [{children}], target: self}}\n"
        f"  - {{instrument: example_worries_temper, datasets: [{children}], target: self}}\n"
        "  - {instrument: example_screen_time, datasets: [copy_child_w2, copy_child_w3], "
        "target: self}\n",
        encoding="utf-8",
    )
    return run_catalog(root)


def grouped_model(result):
    studies = panel.panel_studies(result, X, Y)
    each = [panel.common_waves(result, X, Y, s) for s in studies]
    datasets = list(dict.fromkeys(n for waves in each for _, x, y in waves for n in (x, y)))
    sample = analysis.build_sample(result, datasets, False)
    data = script.AnalysisData(result, sample)

    def variables(key, spot):
        return [data.variable(f"{key}@{'+'.join(w[i][spot] for w in each)}") for i in range(3)]

    model = panel.PanelModel(
        "Stress", "Mood", ["1", "2", "3"], variables(X, 1), variables(Y, 2), ["Mock", "Copy"]
    )
    return model, sample, data.frame()


def test_studies_become_groups_with_their_own_labels(two):
    assert panel.panel_studies(two, X, Y) == ["mock_study", "copy"]
    assert panel.common_waves(two, X, Y, "copy")[0] == ("1", "copy_parent_w1", "copy_child_w1")
    free = panel.syntax(3, True, False, groups=2)
    assert "wy3 ~ c(ay3_g1, ay3_g2)*wy2 + c(cxy3_g1, cxy3_g2)*wx2" in free
    assert "wy3 ~ ay3*wy2 + cxy3*wx2" in panel.syntax(3, True, False, groups=2, across=True)
    model, _, frame = grouped_model(two)
    code = panel.panel_code(model).r
    assert 'group = "study"' in code and "riclpm_equal_studies = fit_panel(" in code
    files = panel.mplus_files(model, frame, "Stress and Mood")
    studies = files["mplus_riclpm_studies.inp"]
    assert "GROUPING = study (1 = g1 2 = g2);" in studies and "wy2 ON wx1 (cxy2);" in studies
    assert "MODEL g2:" in studies and "  [x1 x2 x3 y1 y2 y3];" in studies
    equal = files["mplus_riclpm_equal.inp"]
    assert "wy2 ON wx1 (cxy_g2);" in equal
    assert len(files[panel.DATA].splitlines()[0].split()) == 7


@needs_lavaan
def test_two_studies_with_the_same_data_give_one_studys_paths(two, result):
    model, sample, frame = grouped_model(two)
    found, _ = script.run_code(two, sample, frame, panel.panel_code(model), rscript())
    fit = panel.read_fit(found)
    alone_model, alone_sample, alone_frame = model_of(result)
    alone_found, _ = script.run_code(
        result, alone_sample, alone_frame, panel.panel_code(alone_model), rscript()
    )
    alone = panel.read_fit(alone_found)
    assert fit.n == 2 * alone.n
    for group in (1, 2):
        mine = [p.estimate for p in fit.lagged(panel.RICLPM, "x_to_y", group)]
        assert mine == pytest.approx(
            [p.estimate for p in alone.lagged(panel.RICLPM, "x_to_y")], abs=1e-3
        )
    # The same data in both groups: holding the paths equal across them costs nothing.
    assert fit.tests["studies"][0] == pytest.approx(0, abs=1e-3) and fit.studies_hold
    assert fit.chosen in (panel.STUDIES, panel.EQUAL_STUDIES)
    text = results.panel_text(model, fit)
    assert (
        "With the 2 studies as groups, holding the lagged paths equal across them did not" in text
    )
    assert "In Copy, within people" in text
    columns, rows = panel_view.lagged_table(model, fit)
    assert len(rows) == 2 * 4 * 2 and len(columns) == 1 + 2 * 5
    assert rows[8]["path"].startswith("Copy: X → X, wave 1 to 2")
    _, correlations = panel_view.correlation_table(model, fit)
    assert correlations[0]["what"].startswith("Mock: Random intercepts")
    assert len(panel_view.fit_table(model, fit)[1]) == 5
    assert "Paths equal across studies against free ones" in panel_view.fit_note(fit)
    assert "<svg" in panel_view.diagram(model.waves, fit)
