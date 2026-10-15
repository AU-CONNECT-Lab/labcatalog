import pytest

from labcatalog.charts import views
from labcatalog.charts.style import STATUS_COLORS
from labcatalog.pipeline import run_catalog


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def test_instrument_charts(result):
    assert len(views.score_boxes(result, "example_mood").data) == 6
    assert views.score_distribution(result, "example_mood") is not None
    assert views.item_total(result, "example_mood") is not None
    assert views.item_profile(result, "example_mood") is not None
    assert len(views.item_responses(result, "example_screen_time")) == 2
    assert views.score_boxes(result, "example_screen_time") is None


def test_subscale_radars_need_three_axes(result):
    def titles(instrument_id):
        fig = views.subscale_radars(result, instrument_id)
        return None if fig is None else [a.text for a in fig.layout.annotations]

    assert titles("example_mood") == ["Subscales"]
    assert titles("example_parent_stress") == ["Strain"]
    assert titles("example_child_sleep") is None


def test_small_multiples(result):
    waves = views.wave_profiles(result, "example_mood")
    assert [a.text for a in waves.layout.annotations] == ["Wave 1", "Wave 2", "Wave 3"]
    people = views.people_profiles(result, "example_mood", "child_w1")
    assert [a.text for a in people.layout.annotations] == [
        "Sadness",
        "Worry and fatigue",
        "Low positive affect",
    ]
    background = people.data[0].y
    assert sum(value is None for value in background) == len(result.datasets["child_w1"].frame)


def test_means_and_stability_show_one_instrument(result):
    means = views.score_means(result, "example_mood")
    labels = ["Total score", "Sadness", "Worry and fatigue", "Low positive affect"]
    assert [a.text for a in means.layout.annotations] == labels
    stability = views.stability(result, "example_mood")
    assert list(stability.layout.xaxis.ticktext) == labels


def test_overview_charts(result):
    everything = list(views.correlated_instruments(result))
    assert views.collection_pace(result) is not None
    assert views.correlation_waves(result) == [
        ("mock_study", "1"),
        ("mock_study", "2"),
        ("mock_study", "3"),
    ]
    assert views.score_circle(result, "mock_study", "1", everything) is not None
    assert views.score_circle(result, "mock_study", "1", []) is None


def test_score_ring_shows_every_score_of_the_wave_within_its_range(result):
    assert views.ring_waves(result) == [
        ("mock_study", "1"),
        ("mock_study", "2"),
        ("mock_study", "3"),
    ]
    ring = views.score_ring(result, "mock_study", "1")
    bars = [trace for trace in ring.data if trace.hoveron == "fills"]
    scores = {
        (s.instrument_id, s.score_id)
        for s in result.catalog.scores
        if s.dataset in ("parent_w1", "child_w1")
    }
    assert len(bars) == len(scores)


def test_dot_grid_puts_one_wave_below_the_diagonal_and_another_above(result):
    everything = list(views.correlated_instruments(result))
    grid = views.score_grid(result, everything, ("mock_study", "1"), ("mock_study", "2"))
    hover = next(trace for trace in grid.data if trace.customdata is not None)
    below = {
        wave for (wave, *_), x, y in zip(hover.customdata, hover.x, hover.y, strict=True) if y > x
    }
    above = {
        wave for (wave, *_), x, y in zip(hover.customdata, hover.x, hover.y, strict=True) if y < x
    }
    assert (below, above) == ({"Wave 1"}, {"Wave 2"})
    assert all(x != y for x, y in zip(hover.x, hover.y, strict=True))


def test_item_grid_groups_items_by_subscale(result):
    lower, upper = list(views.item_waves(result, "example_mood"))[:2]
    grid = views.item_grid(result, "example_mood", lower, upper)
    assert list(grid.layout.xaxis.ticktext) == [
        "ems_2",
        "ems_6",
        "ems_3",
        "ems_5",
        "ems_1",
        "ems_4",
    ]


def test_score_correlates_skip_own_subscales_and_put_strongest_first(result):
    total = views.score_correlates(result, "example_mood", "ems_total")
    assert not any(tick.startswith("EMS") for tick in total.layout.xaxis.ticktext)
    sadness = views.score_correlates(result, "example_mood", "ems_sadness")
    assert "EMS worry and fatigue" in sadness.layout.xaxis.ticktext
    points: dict[float, list[float]] = {}
    for trace in sadness.data[1:]:
        for x, y in zip(trace.x, trace.y, strict=True):
            points.setdefault(x, []).append(abs(y))
    strengths = [sum(v) / len(v) for _, v in sorted(points.items())]
    assert strengths == sorted(strengths, reverse=True)


def test_regression_defaults_to_another_instrument(result):
    x = views.default_score(result, "example_mood")
    assert x == "example_mood|ems_total"
    y = views.default_partner(result, x)
    assert y.split("|")[0] != "example_mood"
    assert views.regression(result, x, y) is not None


def test_answer_grid_shows_one_instrument(result):
    assert views.page_count(result, "parent_w1") == 1
    grid = views.answer_grid(result, "parent_w1", 1, "example_parent_stress")
    assert all(tick.startswith("eps_") for tick in grid.layout.yaxis.ticktext)
    colors = [c for trace in grid.data if trace.marker.color for c in trace.marker.color]
    assert STATUS_COLORS["unexpected"] in colors
    assert views.standardized_scores(result, "parent_w1", 1, "example_parent_stress") is not None
