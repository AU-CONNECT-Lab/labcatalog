import plotly.graph_objects as go
from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui.common import heading, note
from labcatalog.pipeline import CatalogResult


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


def instrument_dataset_section(result: CatalogResult, instrument_id: str, dataset: str) -> None:
    profiles = views.people_profiles(result, instrument_id, dataset)
    if profiles is not None:
        heading("Everyone's answers")
        show(profiles)


def overview_section(result: CatalogResult) -> None:
    means = views.score_means(result)
    if means is not None:
        heading("Scores across waves")
        show(means)
    pace = views.collection_pace(result)
    if pace is not None:
        heading("Collection pace")
        show(pace)
    stability = views.stability(result)
    if stability is not None:
        heading("Stability across waves")
        show(stability)


def dataset_section(result: CatalogResult, dataset: str) -> None:
    pages = views.page_count(result, dataset)

    @ui.refreshable
    def people(page: int) -> None:
        heading("Answers by participant")
        show(views.answer_grid(result, dataset, page), "No items are mapped in this dataset.")
        heading("Standardized scores")
        show(views.standardized_scores(result, dataset, page), "No scores in this dataset.")

    if pages > 1:
        with ui.row().classes("items-center gap-2 mt-6"):
            ui.label("Participants page").classes("text-grey-7")
            ui.pagination(
                1, pages, direction_links=True, on_change=lambda e: people.refresh(e.value)
            )
    people(1)


def correlations_page(result: CatalogResult) -> None:
    waves = views.correlation_waves(result)
    if not waves:
        note("No wave has two or more scores to correlate.")
        return
    labels = {f"{study}|{wave}": views.wave_name(result, study, wave) for study, wave in waves}

    @ui.refreshable
    def circle(choice: str) -> None:
        study, wave = choice.split("|")
        show(views.score_circle(result, study, wave))

    heading("How the scores relate")
    ui.toggle(labels, value=next(iter(labels)), on_change=lambda e: circle.refresh(e.value)).props(
        "dense no-caps"
    )
    circle(next(iter(labels)))

    heading("Correlations in every wave")
    show(views.score_matrices(result))

    choices = views.score_choices(result)
    if len(choices) < 2:
        return
    heading("One score against another")
    first, second = views.default_pair(result)
    picked = {"x": first, "y": second}

    @ui.refreshable
    def scatter() -> None:
        show(
            views.regression(result, picked["x"], picked["y"]),
            "These two scores never meet in one wave; see stats.correlate_by in labcatalog.yaml.",
        )

    def choose(axis: str, value: str) -> None:
        picked[axis] = value
        scatter.refresh()

    with ui.row().classes("gap-4"):
        ui.select(choices, value=first, label="X", on_change=lambda e: choose("x", e.value)).props(
            "dense outlined"
        ).classes("w-72")
        ui.select(choices, value=second, label="Y", on_change=lambda e: choose("y", e.value)).props(
            "dense outlined"
        ).classes("w-72")
    scatter()
