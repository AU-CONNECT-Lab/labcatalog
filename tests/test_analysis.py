import pytest

from labcatalog.charts import views
from labcatalog.gui import analysis as page
from labcatalog.gui import common
from labcatalog.gui.common import p_value
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, analysis_script
from labcatalog.stats import multilevel as ml

EMS = "example_mood.ems_total@child_w1"
EPS = "example_parent_stress.eps_mean@parent_w1"


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def test_the_sample_keeps_people_in_every_dataset_or_in_any(result):
    both = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    either = analysis.build_sample(result, ["parent_w1", "child_w1"], False)
    parents = analysis.build_sample(result, ["parent_w1"], True)
    assert len(both.people) <= len(parents.people) <= len(either.people)
    assert set(both.people) <= set(parents.people)
    frame = analysis.table(result, both, [EMS, EPS])
    assert list(frame.index) == both.people


def test_a_pair_matches_the_correlation_of_the_summary(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], False)
    fit = analysis.regress(
        analysis.values(result, sample, EMS), analysis.values(result, sample, EPS)
    )
    wave = next(c for c in result.summary.correlations if c.wave == "1")
    i, j = wave.keys.index(EMS), wave.keys.index(EPS)
    assert fit.correlation.r == pytest.approx(wave.r[i][j])
    assert fit.correlation.n == wave.n[i][j]
    assert fit.correlation.low < fit.correlation.r < fit.correlation.high
    assert fit.correlation.p < 0.05


def test_the_correlation_table_reads_like_apa(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    frame = analysis.table(result, sample, [EMS, EPS])
    matrix = analysis.correlation_matrix(frame)
    described = [analysis.describe(frame[k]) for k in frame.columns]
    columns, rows = page.correlation_table(described, matrix, ["EMS", "EPS"])
    assert [c["label"] for c in columns] == ["Variable", "n", "M", "SD", "1", "2"]
    assert (rows[0]["variable"], rows[0]["c0"], rows[0]["c1"]) == ("1. EMS", "—", "")
    assert rows[1]["c0"].startswith(".") and rows[1]["c0"].endswith("***")
    assert rows[1]["c1"] == "—"
    assert matrix[1][0].n == len(frame.dropna())
    assert views.correlation_chart(result, [EMS, EPS], matrix, ["EMS", "EPS"]) is None


def test_the_heatmap_is_a_lower_triangle_and_the_dots_a_full_matrix(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    keys = views.total_choices(result, sample.datasets)[:3]
    matrix = analysis.correlation_matrix(analysis.table(result, sample, keys))
    labels = ["A", "B", "C"]
    heat = views.correlation_chart(result, keys, matrix, labels).data[0]
    assert (list(heat.x), list(heat.y)) == (["1", "2"], ["2. B", "3. C"])
    assert heat.z[0][0] == pytest.approx(matrix[1][0].r) and heat.z[0][1] is None
    dotted = views.correlation_chart(result, keys, matrix, labels, "dots")
    assert len([s for s in dotted.layout.shapes if s.type == "circle"]) == 6
    assert list(dotted.layout.xaxis.ticktext) == labels and dotted.layout.xaxis.side == "top"
    names = views.instrument_names(result)
    instruments = [views.score_of(result, k).instrument_id for k in keys]
    assert [t.name for t in dotted.data if t.name] == [names[i] for i in instruments]


def test_wave_groups_put_every_reporter_of_a_wave_together(result):
    datasets = ["parent_w1", "child_w1", "child_w2"]
    groups = views.wave_groups(result, datasets, views.variable_choices)
    assert list(groups) == ["Wave 1", "Wave 2"]
    first = {k.rsplit("@", 1)[1] for k in groups["Wave 1"]}
    assert first == {"parent_w1", "child_w1"}
    every = set(views.variable_choices(result, datasets))
    assert set(groups["Wave 1"]) | set(groups["Wave 2"]) == every
    measures = views.wave_groups(result, datasets, analysis_script.measures)
    assert set(measures["Wave 2"]) < set(analysis_script.measures(result, datasets))


def test_choices_come_in_modality_blocks_with_a_shortcut_each(result):
    datasets = ["eeg_w1", "child_w1", "fmri_w1", "eeg_w3", "child_w3"]
    keys = list(views.variable_choices(result, datasets))
    order = [k.rsplit("@", 1)[1] for k in keys]
    assert list(dict.fromkeys(order)) == ["child_w1", "child_w3", "eeg_w1", "eeg_w3", "fmri_w1"]
    menu = views.menu_groups(result, datasets, views.variable_choices)
    assert list(menu) == [
        "All in Wave 1",
        "All in Wave 3",
        "All questionnaires",
        "All EEG",
        "All fMRI",
    ]
    assert {k.rsplit("@", 1)[1] for k in menu["All EEG"]} == {"eeg_w1", "eeg_w3"}
    assert views.menu_groups(result, ["child_w1"], views.variable_choices) == {}


def test_measures_filter_every_list_of_the_page(result):
    measures = list(views.analysis_instruments(result))
    assert measures.index("example_demographics") < measures.index("eeg_resting")
    assert measures.index("eeg_resting") < measures.index("fmri_resting")
    groups = views.instrument_groups(result)
    assert groups["All EEG"] == ["eeg_resting"] and "example_mood" in groups["All questionnaires"]
    view = page.AnalysisView(datasets=["child_w1", "eeg_w1"], instruments=["eeg_resting"])
    choices = page.variables(view)(result, view.datasets)
    assert choices and all(k.startswith("item:eeg_resting.") for k in choices)
    assert page.default_totals(result, view, choices) == []
    outcomes = analysis.of_instruments(ml.outcome_choices(result), ["eeg_resting"])
    assert ml.default_model(result, list(outcomes)).outcome.startswith("item:eeg_resting.")


def test_apa_numbers():
    assert page.apa(0.4512) == ".45"
    assert page.apa(-0.1234) == "-.12"
    assert p_value(0.0004) == "< .001"
    assert p_value(0.0234) == ".023"
    assert page.starred(analysis.Correlation(50, 0.3, 0.02)) == ".30*"
    assert page.starred(analysis.Correlation(2)) == ""


def test_decimal_places_follow_the_setting():
    common.set_decimals(3)
    try:
        assert page.apa(0.4512) == ".451"
        assert page.number(1.23456) == "1.235"
        assert p_value(0.0234) == ".023"
    finally:
        common.set_decimals(2)
    assert page.apa(0.4512) == ".45"
