from datetime import date

import pytest

from labcatalog.charts import network, style, views
from labcatalog.charts.style import STATUS_COLORS
from labcatalog.gui import charts as gui_charts
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def test_instrument_charts(result):
    assert len(views.score_boxes(result, "example_mood").data) == 6
    assert views.score_distribution(result, "example_mood") is not None
    assert len(views.item_responses(result, "example_screen_time")) == 2
    assert views.score_boxes(result, "example_screen_time") is None


def test_subscale_radars_show_the_subscales_then_each_subscale(result):
    def titles(instrument_id):
        fig = views.subscale_radars(result, instrument_id)
        return None if fig is None else [a.text for a in fig.layout.annotations]

    subscales = ["Sadness", "Worry and fatigue", "Low positive affect"]
    assert titles("example_mood") == ["Subscales", *subscales]
    assert views.radar_note(result, "example_mood") == ""
    first = views.subscale_radars(result, "example_mood").data[0]
    assert first.name == "Wave 1"
    assert list(first.theta) == [*subscales, subscales[0]]
    # A sum score per item, so it sits on the same 0 to 3 scale as the item radars.
    sadness = views.summary_of(result, "example_mood.ems_sadness@child_w1")
    assert first.r[0] == pytest.approx(sadness.mean / 3)
    # Two subscales are too few axes for the subscale radar.
    assert titles("example_parent_stress") == ["Strain", "Child-related"]
    stress = views.subscale_radars(result, "example_parent_stress")
    assert list(stress.data[0].theta) == ["eps_1", "eps_3", "eps_5", "eps_1"]


def test_subscales_under_three_items_get_no_radar(mock_project):
    path = mock_project / "instruments" / "example_child_sleep.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("items: [ecs_1, ecs_2, ecs_5]", "items: [ecs_1, ecs_2]"), "utf-8")
    result = run_catalog(mock_project)
    fig = views.subscale_radars(result, "example_child_sleep")
    assert [a.text for a in fig.layout.annotations] == ["Waking"]
    assert views.radar_note(result, "example_child_sleep").startswith("No radar for Settling")


def test_small_multiples(result):
    waves = views.wave_profiles(result, "example_mood")
    assert [a.text for a in waves.layout.annotations] == ["Wave 1", "Wave 2", "Wave 3"]
    people = views.people_profiles(result, "example_mood", "child_w1")
    assert [a.text for a in people.layout.annotations] == [
        "Sadness",
        "Worry and fatigue",
        "Low positive affect",
    ]
    # Everyone is drawn, however many people the file holds.
    background = people.data[0].y
    assert sum(value is None for value in background) == len(result.datasets["child_w1"].frame)


def test_an_instrument_of_numbers_gets_no_answer_scale_charts(result):
    assert views.wave_profiles(result, "eeg_resting") is None
    assert views.subscale_radars(result, "eeg_resting") is None
    assert views.people_profiles(result, "eeg_resting", "eeg_w1") is None
    # Every instrument of the example draws or skips them without an error.
    for instrument_id in result.project.instruments:
        views.wave_profiles(result, instrument_id)
        views.subscale_radars(result, instrument_id)


def test_means_show_one_instrument(result):
    means = views.score_means(result, "example_mood")
    labels = ["Total score", "Sadness", "Worry and fatigue", "Low positive affect"]
    assert [a.text for a in means.layout.annotations] == labels


def test_timeline_draws_waves_up_to_today_and_the_milestones(result):
    today = date(2026, 10, 15)
    fig = views.timeline(result, today)
    assert list(fig.layout.yaxis.categoryarray) == ["Wave 1", "Wave 2", "Wave 3", "Milestones"]
    bars = [t for t in fig.data if t.type == "bar"]
    # Wave 3 has no end yet: a faint bar as long as wave 2 took, a solid one up to today.
    projected, solid = bars[2], bars[3]
    assert projected.base[0] == solid.base[0] == "2026-03-01"
    assert projected.x[0] == (date(2025, 10, 31) - date(2025, 3, 1)).days * 86_400_000
    assert solid.x[0] == (today - date(2026, 3, 1)).days * 86_400_000
    marks = next(t for t in fig.data if t.type == "scatter")
    assert list(marks.text) == ["Interim report", "Wave 3 data freeze"]
    texts = [a.text for a in fig.layout.annotations if a.text != "Today"]
    assert texts == [
        "parent 192, child 217",
        "parent 170, child 182",
        "parent 160 of 170 (94%), child 174 of 182 (96%)",
    ]


def test_overview_charts(result):
    everything = list(views.correlated_instruments(result))
    assert views.collection_pace(result) is not None
    assert views.correlation_waves(result) == [
        ("mock_study", "1"),
        ("mock_study", "2"),
        ("mock_study", "3"),
    ]
    assert views.score_network(result, "mock_study", "1", everything, "instrument") is not None
    assert views.score_network(result, "mock_study", "1", [], "instrument") is None


def test_item_heatmap_and_table_keep_the_item_order_below_the_diagonal(result):
    first = next(iter(views.item_waves(result, "example_mood")))
    items, z, _ = views.item_correlations(result, "example_mood", first)
    assert items == [f"ems_{k}" for k in range(1, 10)]
    grid = views.item_grid(result, "example_mood", first).data[0]
    assert list(grid.x) == [f"{k}. ems_{k}" for k in range(1, 9)]
    assert list(grid.y) == [f"{k}. ems_{k}" for k in range(2, 10)]
    assert grid.z[0][0] == pytest.approx(z[1, 0])
    assert all(v is None for k, row in enumerate(grid.z) for v in row[k + 1 :])
    columns, rows = gui_charts.matrix_table(items, z)
    assert [c["label"] for c in columns] == ["Item", *[str(k) for k in range(1, 10)]]
    assert (rows[0]["variable"], rows[0]["c0"], rows[0]["c1"]) == ("1. ems_1", "—", "")
    assert rows[1]["c0"] == gui_charts.apa(z[1, 0])


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


def test_pair_scatter_plots_the_people_of_the_sample(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    choices = views.variable_choices(result, sample.datasets)
    x, y = "example_mood.ems_total@child_w1", "example_parent_stress.eps_mean@parent_w1"
    # Two files share Wave 1, so the labels name the reporter too.
    assert choices[x] == "EMS total score (Wave 1 · child)"
    assert choices[y] == "EPS mean score (Wave 1 · parent)"
    assert views.total_choices(result, sample.datasets) == [
        x,
        "example_worries_temper.ewt_total@child_w1",
        y,
        "example_child_sleep.ecs_total@parent_w1",
    ]
    fig = views.pair_scatter(result, sample, [x], y)
    both = analysis.table(result, sample, [x, y]).dropna()
    assert len(fig.data[0].x) == len(both)
    # Each X is its own group against the same Y, with the people who have both.
    sleep = "example_child_sleep.ecs_total@parent_w1"
    points = [
        t for t in views.pair_scatter(result, sample, [x, sleep], y).data if t.mode == "markers"
    ]
    assert [t.name.split(" (N=")[0] for t in points] == [choices[x], choices[sleep]]
    assert points[0].marker.color != points[1].marker.color
    assert len(points[1].x) == len(analysis.table(result, sample, [sleep, y]).dropna())


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
    assert views.subscale_radars(result, "example_demographics") is None
    assert views.wave_profiles(result, "example_demographics") is None
    assert views.people_profiles(result, "example_demographics", "parent_w1") is None


def test_number_items_get_one_distribution_per_wave(result):
    age, household = views.number_distributions(result, "example_demographics")
    assert age.layout.xaxis.title.text == "How old is your child (in years)?"
    ticks = age.layout.yaxis.ticktext
    assert len(ticks) == 3 and all("n " in tick for tick in ticks)
    assert household.layout.xaxis.range[0] < 2 < 7 < household.layout.xaxis.range[1]
    assert views.number_distributions(result, "example_mood") == []


def test_score_network_links_strong_pairs_and_colours_by_the_first_matching_tag(result):
    everything = list(views.correlated_instruments(result))
    assert list(views.network_colorings(result)) == [
        "instrument",
        "cluster",
        "facet:reporter",
        "facet:target",
        "facet:modality",
        "facet:domain",
        "facet:topics",
    ]
    spec = views.score_network(result, "mock_study", "1", everything, "facet:topics")
    names = [n["name"] for n in spec["nodes"]]
    groups = [g["name"] for g in spec["groups"]]
    assert groups == ["negative affect", "positive affect", "parenting", "sleep"]
    strain = spec["nodes"][names.index("EPS strain")]
    assert groups[strain["group"]] == "negative affect"
    name_of = {n["id"]: n["name"] for n in spec["nodes"]}
    linked = {frozenset((name_of[e["source"]], name_of[e["target"]])) for e in spec["links"]}
    assert frozenset(("EMS total score", "EMS sadness")) not in linked
    assert all(e["value"] >= 0.3 for e in spec["links"])
    for color_by in views.network_colorings(result):
        spec = views.score_network(result, "mock_study", "1", everything, color_by)
        used = {n["group"] for n in spec["nodes"]}
        assert used <= set(range(len(spec["groups"])))


def test_network_colours_the_instruments_shown_in_palette_order(result):
    everything = list(views.correlated_instruments(result))
    spec = views.score_network(result, "mock_study", "1", everything, "instrument")
    colors = [g["color"] for g in spec["groups"]]
    assert colors == [style.group_color(k) for k in range(len(colors))]
    # A weak link is drawn from the stronger part of the scale, not near white.
    weakest = min(spec["links"], key=lambda e: e["value"])
    assert weakest["color"] != style.scale_color(weakest["value"], style.CORRELATION_SCALE, -1, 1)


def test_network_links_by_id_and_tightens_with_many_nodes():
    def spec(n: int) -> dict:
        nodes = [{"key": f"s{i}", "label": f"S{i}", "category": 0, "tip": ""} for i in range(n)]
        links = [{"source": 0, "target": 1, "r": 0.5, "tip": ""}]
        return network.score_network(nodes, links, [("All", "#000")])

    few, many = spec(10), spec(90)
    assert few["links"][0] == {**few["links"][0], "source": "s0", "target": "s1"}
    assert many["force"]["length"][1] < few["force"]["length"][1]
    assert many["force"]["gravity"] > few["force"]["gravity"]
    assert many["force"]["repel"] < few["force"]["repel"]


def test_catalog_map_hangs_items_from_their_smallest_score_and_links_scores_across_instruments(
    result,
):
    instruments = list(result.project.instruments)
    spec = views.catalog_map(result, instruments)
    ids = {n["id"] for n in spec["nodes"]}
    assert {f"i:{i}" for i in instruments} <= ids
    parents = {
        link["target"]: link["source"]
        for link in spec["links"]
        if link["color"] == network.UNSET_COLOR
    }
    mood = result.project.instruments["example_mood"]
    for item in mood.items:
        holders = [s for s in mood.scores if item.id in s.items]
        if holders:
            smallest = min(holders, key=lambda s: len(s.items))
            assert parents[f"t:example_mood:{item.id}"] == f"s:example_mood:{smallest.id}"
    correlated = [link for link in spec["links"] if link["color"] != network.UNSET_COLOR]
    assert correlated
    assert all(link["source"].split(":")[1] != link["target"].split(":")[1] for link in correlated)
    assert all(link["value"] < 1 for link in correlated)
    assert sum(n.get("named", False) for n in spec["nodes"]) == len(instruments)
    assert views.catalog_map(result, []) is None
