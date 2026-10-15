import plotly.graph_objects as go
from nicegui import ui

from labcatalog.charts import network, views
from labcatalog.gui import theme
from labcatalog.gui.common import card, heading, note, section
from labcatalog.pipeline import CatalogResult


def show(fig: go.Figure | None, empty: str = "") -> ui.plotly | None:
    if fig is None:
        if empty:
            note(empty)
        return None
    height = (fig.layout.height or 400) + 8
    return (
        ui.plotly({**theme.for_page(fig.to_plotly_json()), "config": {"displayModeBar": False}})
        .classes("w-full")
        .style(f"height:{height}px")
    )


def side_by_side(*panels: tuple[str, go.Figure | None]) -> None:
    # Panels share the row equally; a missing figure leaves the row to the others.
    shown = [(title, fig) for title, fig in panels if fig is not None]
    if not shown:
        return
    with ui.row().classes("w-full gap-4 no-wrap items-start"):
        for title, fig in shown:
            with ui.column().classes("flex-1 min-w-0 gap-0"):
                if title:
                    heading(title)
                show(fig)


def instrument_section(result: CatalogResult, instrument_id: str) -> None:
    if not views.instrument_datasets(result, instrument_id):
        return
    section("Across waves")
    side_by_side(
        ("", views.score_boxes(result, instrument_id)),
        ("", views.score_distribution(result, instrument_id)),
    )
    for fig in views.item_responses(result, instrument_id):
        show(fig)
    item_means(result, instrument_id)
    means = views.score_means(result, instrument_id)
    if means is not None:
        heading("Scores across waves")
        show(means)
    profiles = views.wave_profiles(result, instrument_id)
    if profiles is not None:
        heading("Each wave against the others")
        show(profiles)
    waves = views.item_waves(result, instrument_id)
    if waves:
        heading("Item correlations")
        one_wave(waves, lambda dataset: show(views.item_grid(result, instrument_id, dataset)))
    other_scores(result, instrument_id)


def item_means(result: CatalogResult, instrument_id: str) -> None:
    radars = views.subscale_radars(result, instrument_id)
    if radars is None:
        return
    heading("Item means")
    if views.radar_note(result, instrument_id):
        note(views.radar_note(result, instrument_id))
    show(radars)


def other_scores(result: CatalogResult, instrument_id: str) -> None:
    own = views.instrument_choices(result, instrument_id)
    if not own or len(views.score_choices(result)) < 2:
        return
    first = views.default_score(result, instrument_id)

    @ui.refreshable
    def correlates(choice: str) -> None:
        show(
            views.score_correlates(result, *choice.split("|")),
            "No other score was measured in the same wave.",
        )

    heading("Against other scores")
    if len(own) > 1:
        ui.select(
            own, value=first, label="Score", on_change=lambda e: correlates.refresh(e.value)
        ).props("dense outlined").classes("w-72")
    correlates(first)


def instrument_dataset_section(result: CatalogResult, instrument_id: str, dataset: str) -> None:
    profiles = views.people_profiles(result, instrument_id, dataset)
    if profiles is not None:
        heading("Everyone's answers")
        show(profiles)
    pages = views.page_count(result, dataset)

    @ui.refreshable
    def people(page: int) -> None:
        heading("Answers by participant")
        show(
            views.answer_grid(result, dataset, page, instrument_id),
            "No items of this instrument are mapped in this dataset.",
        )
        standardized = views.standardized_scores(result, dataset, page, instrument_id)
        if standardized is not None:
            heading("Standardized scores")
            show(standardized)

    if pages > 1:
        with ui.row().classes("items-center gap-2 mt-6"):
            ui.label("Participants page").classes("text-grey-7")
            ui.pagination(
                1, pages, direction_links=True, on_change=lambda e: people.refresh(e.value)
            )
    people(1)


def overview_section(result: CatalogResult) -> None:
    timeline(result)
    pace = views.collection_pace(result)
    if pace is not None:
        with card("Collection pace", "People with data, by week since each wave started"):
            show(pace)
    levels = views.score_levels(result)
    if levels is not None:
        with card("Scores in each wave", "Mean score as a share of its possible range"):
            show(levels)
    score_relations(result)


def wave_picker(choices: dict[str, str], value: str, changed) -> None:
    ui.select(choices, value=value, label="Wave", on_change=lambda e: changed(e.value)).props(
        "dense outlined"
    ).classes("w-56")


def one_wave(choices: dict[str, str], render) -> None:
    @ui.refreshable
    def grid(choice: str) -> None:
        render(choice)

    wave_picker(choices, next(iter(choices)), grid.refresh)
    grid(next(iter(choices)))


def score_relations(result: CatalogResult) -> None:
    waves = views.correlation_waves(result)
    if not waves:
        return
    instruments = views.correlated_instruments(result)
    choices = {f"{study}|{wave}": views.wave_name(result, study, wave) for study, wave in waves}
    picked = {
        "wave": next(iter(choices)),
        "instruments": list(instruments),
        "color": "instrument",
    }

    @ui.refreshable
    def grid() -> None:
        show(
            views.score_grid(
                result,
                picked["instruments"],
                tuple(picked["wave"].split("|")),
            ),
            "Pick instruments with at least two scores.",
        )

    @ui.refreshable
    def graph() -> None:
        study, wave = picked["wave"].split("|")
        show_network(
            views.score_network(result, study, wave, picked["instruments"], picked["color"])
        )

    def changed(key: str, value) -> None:
        picked[key] = value or []
        if key == "instruments":
            chooser.props(f'display-value="{shown()}"')
        grid.refresh()
        graph.refresh()

    def recolor(value: str) -> None:
        picked["color"] = value
        graph.refresh()

    def shown() -> str:
        return f"{len(picked['instruments'])} of {len(instruments)} instruments"

    with card("How the scores relate", "Pearson r between scores measured in one wave") as tools:
        with tools:
            chooser = (
                ui.select(
                    instruments,
                    multiple=True,
                    value=picked["instruments"],
                    label="Instruments",
                    on_change=lambda e: changed("instruments", e.value),
                )
                .props(f'dense outlined clearable display-value="{shown()}"')
                .classes("w-64")
            )
            wave_picker(choices, picked["wave"], lambda value: changed("wave", value))
        grid()
        ui.select(
            views.network_colorings(result),
            value=picked["color"],
            label="Color by",
            on_change=lambda e: recolor(e.value),
        ).props("dense outlined").classes("w-56 self-end")
        graph()


def show_network(option: dict | None) -> None:
    if option is None:
        return
    ui.echart(theme.echart_for_page(option)).classes("w-full").style(
        f"height:{network.NETWORK_HEIGHT}px"
    )


def timeline(result: CatalogResult) -> None:
    fig = views.timeline(result)
    if fig is not None:
        with card(
            "Timeline", "Each wave's dates and counts, and the milestones in labcatalog.yaml"
        ):
            show(fig)
