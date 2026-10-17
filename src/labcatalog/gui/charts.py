import numpy as np
import plotly.graph_objects as go
from nicegui import ui

from labcatalog import defaults
from labcatalog.charts import network, views
from labcatalog.gui import theme
from labcatalog.gui.common import apa, caption, col, note, panel, table
from labcatalog.pipeline import CatalogResult

TABLE_MIN = 360


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
                    caption(title)
                show(fig)


def score_charts(result: CatalogResult, instrument_id: str) -> None:
    boxes = views.score_boxes(result, instrument_id)
    spread = views.score_distribution(result, instrument_id)
    if boxes is not None or spread is not None:
        with panel("Distributions", "Each score by wave, and the total score's density"):
            side_by_side(("", boxes), ("", spread))
    means = views.score_means(result, instrument_id)
    if means is not None:
        with panel("Scores across waves"):
            show(means)


def item_charts(result: CatalogResult, instrument_id: str) -> None:
    responses = [
        *views.item_responses(result, instrument_id),
        *views.number_distributions(result, instrument_id),
    ]
    if responses:
        with panel("Item responses"):
            for fig in responses:
                show(fig)
    item_means(result, instrument_id)
    profiles = views.wave_profiles(result, instrument_id)
    if profiles is not None:
        with panel("Each wave against the others"):
            show(profiles)


def item_correlation_section(result: CatalogResult, instrument_id: str) -> None:
    waves = views.item_waves(result, instrument_id)
    if waves:
        with panel("Item correlations") as tools:
            one_wave(
                waves, lambda dataset: item_correlations(result, instrument_id, dataset), tools
            )


def figure_column(fig: go.Figure) -> ui.column:
    return ui.column().classes("gap-1").style(f"width:{fig.layout.width}px")


def rest_column() -> ui.column:
    # Sits right of a figure_column, or wraps below it when the page is too narrow.
    return ui.column().classes("gap-1 min-w-0").style(f"flex: 1 1 {TABLE_MIN}px")


def item_correlations(result: CatalogResult, instrument_id: str, dataset: str) -> None:
    items, z, n = views.item_correlations(result, instrument_id, dataset)
    if len(items) < 2:
        return
    fig = views.item_grid(result, instrument_id, dataset)
    with ui.row().classes("w-full gap-6 items-start"):
        if fig is not None:
            with figure_column(fig):
                show(fig)
        with rest_column():
            table(*matrix_table(items, z))
            note(f"Spearman ρ on the {n} people who answered every item.")


def matrix_table(labels: list[str], z: np.ndarray) -> tuple[list[dict], list[dict]]:
    columns = [
        col("variable", "Item"),
        *[col(f"c{j}", str(j + 1), numeric=True, sortable=False) for j in range(len(labels))],
    ]
    rows = [
        {
            "variable": f"{i + 1}. {label}",
            **{
                f"c{j}": (apa(z[i, j]) if np.isfinite(z[i, j]) else "")
                if j < i
                else ("—" if j == i else "")
                for j in range(len(labels))
            },
        }
        for i, label in enumerate(labels)
    ]
    return columns, rows


def item_means(result: CatalogResult, instrument_id: str) -> None:
    radars = views.subscale_radars(result, instrument_id)
    if radars is None:
        return
    with panel("Item means", views.radar_note(result, instrument_id) or ""):
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

    with panel("Against other scores") as tools:
        if len(own) > 1:
            with tools:
                ui.select(
                    own, value=first, label="Score", on_change=lambda e: correlates.refresh(e.value)
                ).classes("w-64")
        correlates(first)


def instrument_dataset_section(result: CatalogResult, instrument_id: str, dataset: str) -> None:
    profiles = views.people_profiles(result, instrument_id, dataset)
    if profiles is not None:
        with panel("Everyone's answers"):
            show(profiles)
    pages = views.page_count(result, dataset)

    @ui.refreshable
    def answers(page: int) -> None:
        show(
            views.answer_grid(result, dataset, page, instrument_id),
            "No items of this instrument are mapped in this dataset.",
        )

    @ui.refreshable
    def standardized(page: int) -> None:
        fig = views.standardized_scores(result, dataset, page, instrument_id)
        if fig is not None:
            with panel("Standardized scores"):
                show(fig)

    def turn(page: int) -> None:
        answers.refresh(page)
        standardized.refresh(page)

    with panel("Answers by participant") as tools:
        if pages > 1:
            with tools:
                ui.label("Page").classes("lc-note")
                ui.pagination(1, pages, direction_links=True, on_change=lambda e: turn(e.value))
        answers(1)
    standardized(1)


def overview_section(result: CatalogResult) -> None:
    timeline(result)
    pace = views.collection_pace(result)
    if pace is not None:
        with panel("Collection pace", "Rows with a date, by week since each wave started"):
            show(pace)
    levels = views.score_levels(result)
    if levels is not None:
        with panel("Scores in each wave", "Mean score as a share of its possible range"):
            show(levels)
    score_relations(result)


def wave_picker(choices: dict[str, str], value: str, changed) -> None:
    ui.select(choices, value=value, label="Wave", on_change=lambda e: changed(e.value)).props(
        "dense outlined"
    ).classes("w-56")


def one_wave(choices: dict[str, str], render, tools: ui.row) -> None:
    @ui.refreshable
    def grid(choice: str) -> None:
        render(choice)

    with tools:
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

    drawn: dict = {"chart": None}

    def graph() -> None:
        study, wave = picked["wave"].split("|")
        option = views.score_network(result, study, wave, picked["instruments"], picked["color"])
        chart = drawn["chart"]
        # Updating the same chart keeps every node where it is, so the layout only drifts.
        if option is not None and chart is not None:
            chart.options.clear()
            chart.options.update(theme.echart_for_page(option))
            chart.update()
            return
        holder.clear()
        with holder:
            drawn["chart"] = show_network(option, "Pick instruments with at least two scores.")

    def changed(key: str, value) -> None:
        picked[key] = value or []
        if key == "instruments":
            chooser.props(f'display-value="{shown()}"')
        graph()

    def shown() -> str:
        return f"{len(picked['instruments'])} of {len(instruments)} instruments"

    coefficient = result.project.config.stats.coefficient()
    with panel(
        "How the scores relate",
        f"{coefficient} between scores measured in one wave, linked at |r| ≥ "
        f"{defaults.CHART_MIN_R:g}. Drag to move, scroll to zoom.",
    ) as tools:
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
            ui.select(
                views.network_colorings(result),
                value=picked["color"],
                label="Color by",
                on_change=lambda e: changed("color", e.value),
            ).props("dense outlined").classes("w-56")
        holder = ui.element("div").classes("w-full")
        graph()


def show_network(option: dict | None, empty: str) -> ui.echart | None:
    if option is None:
        note(empty)
        return None
    return (
        ui.echart(theme.echart_for_page(option))
        .classes("w-full")
        .style(f"height:{network.NETWORK_HEIGHT}px")
    )


def timeline(result: CatalogResult) -> None:
    fig = views.timeline(result)
    if fig is not None:
        with panel(
            "Timeline", "Each wave's dates and counts, and the milestones in labcatalog.yaml"
        ):
            show(fig)
