import pytest

from labcatalog.charts import views
from labcatalog.charts.style import STATUS_COLORS
from labcatalog.pipeline import run_catalog


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def test_instrument_charts(result):
    assert len(views.score_boxes(result, "example_mood").data) == 4
    assert views.score_distribution(result, "example_mood") is not None
    assert views.item_total(result, "example_mood") is not None
    assert views.item_profile(result, "example_mood") is not None
    assert views.item_correlations(result, "example_mood") is not None
    assert len(views.item_responses(result, "example_screen_time")) == 2
    assert views.score_boxes(result, "example_screen_time") is None


def test_subscale_radar_needs_three_subscales(result):
    assert views.subscale_profile(result, "example_mood") is not None
    assert views.subscale_profile(result, "example_parent_stress") is None


def test_small_multiples(result):
    waves = views.wave_profiles(result, "example_mood")
    assert [a.text for a in waves.layout.annotations] == ["Wave 1", "Wave 2"]
    people = views.people_profiles(result, "example_mood", "child_w1")
    assert [a.text for a in people.layout.annotations] == [
        "Sadness",
        "Worry and fatigue",
        "Low positive affect",
    ]
    background = people.data[0].y
    assert sum(value is None for value in background) == len(result.datasets["child_w1"].frame)


def test_overview_charts(result):
    assert views.score_means(result) is not None
    assert views.collection_pace(result) is not None
    assert views.stability(result) is not None


def test_correlation_charts(result):
    assert views.correlation_waves(result) == [("mock_study", "1"), ("mock_study", "2")]
    assert views.score_circle(result, "mock_study", "1") is not None
    assert views.score_matrices(result) is not None
    x, y = views.default_pair(result)
    assert x.split("|")[0] != y.split("|")[0]
    assert views.regression(result, x, y) is not None


def test_answer_grid_marks_values_that_are_not_options(result):
    assert views.page_count(result, "parent_w1") == 1
    grid = views.answer_grid(result, "parent_w1", 1)
    colors = [c for trace in grid.data if trace.marker.color for c in trace.marker.color]
    assert STATUS_COLORS["unexpected"] in colors
    assert views.standardized_scores(result, "parent_w1", 1) is not None
