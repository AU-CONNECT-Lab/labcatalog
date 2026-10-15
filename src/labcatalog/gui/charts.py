import plotly.graph_objects as go
from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui.common import heading, note
from labcatalog.pipeline import CatalogResult

NO_SHARED_WAVE = (
    "These two scores never meet in one wave; see stats.correlate_by in labcatalog.yaml."
)


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
    subscales = views.subscale_radars(result, instrument_id)
    if subscales is not None:
        heading("Subscales")
        show(subscales)
    waves = views.item_waves(result, instrument_id)
    if waves:
        heading("Item correlations")
        triangles(waves, lambda lower, upper: views.item_grid(result, instrument_id, lower, upper))
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
    score_levels(result)
    score_relations(result)


def score_levels(result: CatalogResult) -> None:
    waves = views.level_waves(result)
    if not waves:
        return
    choices = {f"{study}|{wave}": views.wave_name(result, study, wave) for study, wave in waves}

    @ui.refreshable
    def bars(choice: str) -> None:
        show(views.score_levels(result, *choice.split("|")))

    heading("Scores in each wave")
    ui.toggle(choices, value=next(iter(choices)), on_change=lambda e: bars.refresh(e.value)).props(
        "dense no-caps"
    )
    bars(next(iter(choices)))


def first_two(choices: dict[str, str]) -> tuple[str, str]:
    keys = list(choices)
    return keys[0], keys[1] if len(keys) > 1 else keys[0]


def wave_pickers(choices: dict[str, str], picked: dict, changed) -> None:
    for key, label in (("lower", "Below the diagonal"), ("upper", "Above the diagonal")):
        ui.select(
            choices,
            value=picked[key],
            label=label,
            on_change=lambda e, k=key: changed(k, e.value),
        ).props("dense outlined").classes("w-56")


def triangles(choices: dict[str, str], build) -> None:
    lower, upper = first_two(choices)
    picked = {"lower": lower, "upper": upper}

    @ui.refreshable
    def grid() -> None:
        show(build(picked["lower"], picked["upper"]))

    def changed(key: str, value: str) -> None:
        picked[key] = value
        grid.refresh()

    with ui.row().classes("items-center gap-4"):
        wave_pickers(choices, picked, changed)
    grid()


def score_relations(result: CatalogResult) -> None:
    waves = views.correlation_waves(result)
    if not waves:
        return
    instruments = views.correlated_instruments(result)
    choices = {f"{study}|{wave}": views.wave_name(result, study, wave) for study, wave in waves}
    lower, upper = first_two(choices)
    picked = {"lower": lower, "upper": upper, "instruments": list(instruments)}

    @ui.refreshable
    def grid() -> None:
        show(
            views.score_grid(
                result,
                picked["instruments"],
                tuple(picked["lower"].split("|")),
                tuple(picked["upper"].split("|")),
            ),
            "Pick instruments with at least two scores.",
        )

    @ui.refreshable
    def circle() -> None:
        study, wave = picked["lower"].split("|")
        show(views.score_circle(result, study, wave, picked["instruments"]))

    def changed(key: str, value) -> None:
        picked[key] = value or []
        if key == "instruments":
            chooser.props(f'display-value="{shown()}"')
        grid.refresh()
        circle.refresh()

    def shown() -> str:
        return f"{len(picked['instruments'])} of {len(instruments)} instruments"

    heading("How the scores relate")
    with ui.row().classes("items-center gap-4"):
        chooser = (
            ui.select(
                instruments,
                multiple=True,
                value=picked["instruments"],
                label="Instruments",
                on_change=lambda e: changed("instruments", e.value),
            )
            .props(f'dense outlined clearable display-value="{shown()}"')
            .classes("w-72")
        )
        wave_pickers(choices, picked, changed)
    grid()
    circle()
