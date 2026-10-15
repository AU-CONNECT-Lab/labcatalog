import pytest

from labcatalog import analysis
from labcatalog.gui import analysis as page
from labcatalog.pipeline import run_catalog

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
    keys = [EMS, EPS]
    columns, rows, pairs = page.correlation_table(result, sample, keys, {EMS: "EMS", EPS: "EPS"})
    assert [c["label"] for c in columns] == ["Variable", "n", "M", "SD", "1", "2"]
    assert (rows[0]["variable"], rows[0]["c0"], rows[0]["c1"]) == ("1. EMS", "—", "")
    assert rows[1]["c0"].startswith(".") and rows[1]["c0"].endswith("***")
    assert rows[1]["c1"] == "—"
    assert pairs == [rows[1]["n"] if rows[1]["n"] <= rows[0]["n"] else pairs[0]]


def test_apa_numbers():
    assert page.apa(0.4512) == ".45"
    assert page.apa(-0.1234) == "-.12"
    assert page.p_value(0.0004) == "< .001"
    assert page.p_value(0.0234) == ".023"
    assert page.starred(analysis.Correlation(50, 0.3, 0.02)) == ".30*"
    assert page.starred(analysis.Correlation(2)) == ""
