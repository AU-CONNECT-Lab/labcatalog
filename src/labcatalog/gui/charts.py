import plotly.graph_objects as go
from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui.common import heading, note
from labcatalog.pipeline import CatalogResult

NO_SHARED_WAVE = "These two scores never meet in one wave; see stats.correlate_by in labcatalog.yaml."


def show(fig: go.Figure | None, empty: str = "") -> None:
    if fig is None:
        if empty:
            note(empty)
        return
    height = (fig.layout.height or 400) + 8
    ui.plotly({**fig.to_plotly_json(), "config": {"displayModeBar": False}}).classes(
        "w-full"
    ).style(f"height:{height}px")


def instrument_section(result: CatalogResult, instrument_id: str) -> None:
    if not views.instrument_datasets(result, instrument_id):
        return
    heading("Across waves")
    with ui.row().classes("w-full gap-4 no-wrap items-start"):
        with ui.column().classes("w-1/2"):
            show(views.score_boxes(result, instrument_id))
        with ui.column().classes("w-1/2"):
            show(views.score_distribution(result, instrument_id))
    for fig in views.item_responses(result, instrument_id):
        show(fig)
    with ui.row().classes("w-full gap-4 no-wrap items-start"):
        with ui.column().classes("w-1/2"):
            show(views.item_total(result, instrument_id))
        with ui.column().classes("w-1/2"):
            show(views.item_profile(result, instrument_id))
    means = views.score_means(result, instrument_id)
    if means is not None:
        heading("Scores across waves")
        show(means)
    stability = views.stability(result, instrument_id)
    if stability is not None:
        heading("Stability across waves")
        show(stability)
    profiles = views.wave_profiles(result, instrument_id)
    if profiles is not None:
        heading("Each wave against the others")
        show(profiles)
    subscales = views.subscale_profile(result, instrument_id)
    if subscales is not None:
        heading("Subscales")
        show(subscales)
    correlations = views.item_correlations(result, instrument_id)
    if correlations is not None:
        heading("Item correlations")
        show(correlations)
    other_scores(result, instrument_id)


def other_scores(result: CatalogResult, instrument_id: str) -> None:
    own = views.instrument_choices(result, instrument_id)
    if not own or len(views.score_choices(result)) < 2:
        return
    first = views.default_score(result, instrument_id)
    picked = {"x": first, "y": views.default_partner(result, first)}

    @ui.refreshable
    def correlates() -> None:
        show(
            views.score_correlates(result, *picked["x"].split("|")),
            "No other score was measured in the same wave.",
        )

    @ui.refreshable
    def scatter() -> None:
        show(views.regression(result, picked["x"], picked["y"]), NO_SHARED_WAVE)

    def choose(axis: str, value: str) -> None:
        picked[axis] = value
        if axis == "x":
            correlates.refresh()
        scatter.refresh()

    heading("Against other scores")
    if len(own) > 1:
        ui.select(own, value=first, label="Score", on_change=lambda e: choose("x", e.value)).props(
            "dense outlined"
        ).classes("w-72")
    correlates()
    ui.select(
        views.score_choices(result),
        value=picked["y"],
        label="Against",
        with_input=True,
        on_change=lambda e: choose("y", e.value),
    ).props("dense outlined").classes("w-72 mt-4")
    scatter()


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
    pace = views.collection_pace(result)
    if pace is not None:
        heading("Collection pace")
        show(pace)
    score_relations(result)


def score_relations(result: CatalogResult) -> None:
    waves = views.correlation_waves(result)
    instruments = views.correlated_instruments(result)
    if not waves:
        return
    labels = {f"{study}|{wave}": views.wave_name(result, study, wave) for study, wave in waves}
    picked = {"wave": next(iter(labels)), "instruments": list(instruments)}

    @ui.refreshable
    def circle() -> None:
        study, wave = picked["wave"].split("|")
        show(
            views.score_circle(result, study, wave, picked["instruments"]),
            "Pick instruments with at least two scores measured in this wave.",
        )

    @ui.refreshable
    def matrices() -> None:
        show(views.score_matrices(result, picked["instruments"]))

    def choose_wave(value: str) -> None:
        picked["wave"] = value
        circle.refresh()

    def choose_instruments(value: list[str] | None) -> None:
        picked["instruments"] = value or []
        chooser.props(f'display-value="{shown(picked["instruments"])}"')
        circle.refresh()
        matrices.refresh()

    def shown(chosen: list[str]) -> str:
        return f"{len(chosen)} of {len(instruments)} instruments"

    heading("How the scores relate")
    with ui.row().classes("items-center gap-4"):
        chooser = (
            ui.select(
                instruments,
                multiple=True,
                value=picked["instruments"],
                label="Instruments",
                on_change=lambda e: choose_instruments(e.value),
            )
            .props(f'dense outlined clearable display-value="{shown(picked["instruments"])}"')
            .classes("w-72")
        )
        ui.toggle(labels, value=picked["wave"], on_change=lambda e: choose_wave(e.value)).props(
            "dense no-caps"
        )
    circle()
    heading("Correlations in every wave")
    matrices()
