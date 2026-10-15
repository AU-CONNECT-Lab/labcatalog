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


def test_subscale_radars_draw_each_subscale_with_three_items(result):
    def titles(instrument_id):
        fig = views.subscale_radars(result, instrument_id)
        return None if fig is None else [a.text for a in fig.layout.annotations]

    assert titles("example_mood") is None
    assert views.short_subscales(result, "example_mood") == [
        "Sadness",
        "Worry and fatigue",
        "Low positive affect",
    ]
    assert titles("example_parent_stress") == ["Strain"]
    assert views.short_subscales(result, "example_parent_stress") == ["Child-related"]
    radar = views.subscale_radars(result, "example_parent_stress")
    assert [trace.name for trace in radar.data] == ["Wave 1", "Wave 2", "Wave 3"]


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
    assert list(stability.layout.yaxis.ticktext) == labels


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


def test_score_levels_put_every_wave_on_one_row_per_score(result):
    fig = views.score_levels(result)
    waves = fig.data[1:]
    assert [w.name for w in waves] == ["Wave 1", "Wave 2", "Wave 3"]
    scores = {(s.instrument_id, s.score_id) for s in result.catalog.scores}
    assert len(fig.layout.yaxis.ticktext) == len(scores)
    wave_1 = {
        (s.instrument_id, s.score_id)
        for s in result.catalog.scores
        if s.dataset in ("parent_w1", "child_w1")
    }
    assert len(waves[0].x) == len(wave_1)
    assert all(0 <= share <= 1 for w in waves for share in w.x)


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
    by_subscale = ["ems_2", "ems_6", "ems_3", "ems_5", "ems_1", "ems_4"]
    assert list(grid.layout.xaxis.ticktext) == by_subscale
    circle = views.item_circle(result, "example_mood", lower)
    labels = [a.text for a in circle.layout.annotations]
    assert labels == by_subscale
    assert circle.layout.title.text.startswith("Wave 1: |Spearman ρ| ≥ 0.3")


def test_score_correlates_skip_own_subscales_and_put_strongest_first(result):
    total = views.score_correlates(result, "example_mood", "ems_total")
    assert not any(tick.startswith("EMS") for tick in total.layout.yaxis.ticktext)
    sadness = views.score_correlates(result, "example_mood", "ems_sadness")
    assert "EMS worry and fatigue" in sadness.layout.yaxis.ticktext
    rows: dict[float, list[float]] = {}
    for trace in sadness.data[1:]:
        for x, y in zip(trace.x, trace.y, strict=True):
            rows.setdefault(y, []).append(abs(x))
    strengths = [sum(v) / len(v) for _, v in sorted(rows.items())]
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


def test_number_and_text_items_are_left_out_of_option_charts(result):
    assert len(views.item_responses(result, "example_demographics")) == 2
    grid = views.answer_grid(result, "parent_w2", 1, "example_demographics")
    assert all(tick.startswith(("dem_gender", "dem_edu")) for tick in grid.layout.yaxis.ticktext)
    assert views.item_profile(result, "example_demographics") is None
    waves = views.wave_profiles(result, "example_demographics")
    assert len(waves.data[-1].x) == 2


def test_score_network_links_strong_pairs_and_colours_by_the_first_matching_tag(result):
    everything = list(views.correlated_instruments(result))
    assert list(views.network_colorings(result)) == [
        "instrument",
        "cluster",
        "facet:reporter",
        "facet:domain",
        "facet:topics",
    ]
    option = views.score_network(result, "mock_study", "1", everything, "facet:topics")
    series = option["series"][0]
    names = [n["name"] for n in series["data"]]
    categories = [c["name"] for c in series["categories"]]
    assert categories == ["negative affect", "positive affect", "parenting", "sleep"]
    strain = series["data"][names.index("EPS strain")]
    assert categories[strain["category"]] == "negative affect"
    linked = {
        frozenset((names[int(e["source"])], names[int(e["target"])])) for e in series["links"]
    }
    assert frozenset(("EMS total score", "EMS sadness")) not in linked
    assert all(e["value"] >= 0.3 for e in series["links"])
    for color_by in views.network_colorings(result):
        option = views.score_network(result, "mock_study", "1", everything, color_by)
        used = {n["category"] for n in option["series"][0]["data"]}
        assert used <= set(range(len(option["series"][0]["categories"])))
