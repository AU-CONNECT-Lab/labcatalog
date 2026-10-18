from collections.abc import Callable

from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui import charts, theme
from labcatalog.gui.common import panel, sorted_waves, unique
from labcatalog.metadata.completeness import gaps
from labcatalog.pipeline import CatalogResult

# Icon and colour of each kind of to-do row.
TODO_LOOK = {
    views.ERRORS: ("error", "bad"),
    views.DETAILS: ("edit_note", "info"),
    views.COLLECTING: ("hourglass_top", "ok"),
    views.WARNINGS: ("warning", "warn"),
}


def render(
    result: CatalogResult,
    on_instruments: Callable[[], None],
    on_datasets: Callable[[], None],
    on_problems: Callable[[], None],
) -> None:
    config = result.project.config
    issues = result.report.issues
    errors = sum(i.level == "error" for i in issues)
    warnings = sum(i.level == "warning" for i in issues)
    unfinished = sum(bool(gaps(i)) for i in result.project.instruments.values())
    waves = sorted_waves(d.wave for d in config.datasets)
    reporters = unique(d.reporter for d in config.datasets)
    banner(result)
    with ui.grid(columns=4).classes("lc-lifted w-full gap-4"):
        tile(
            "Instruments",
            len(result.project.instruments),
            "list_alt",
            f"{unfinished} with details missing" if unfinished else "All details filled in",
            on_instruments,
        )
        tile(
            "Datasets",
            len(config.datasets),
            "table_chart",
            f"{len(waves)} waves, {len(reporters)} reporters",
            on_datasets,
        )
        tile(
            "Errors",
            errors,
            "error",
            "Fix before analysis" if errors else "None",
            on_problems,
            "bad" if errors else "ok",
        )
        tile(
            "Warnings",
            warnings,
            "warning",
            "Worth a look" if warnings else "None",
            on_problems,
            "warn" if warnings else "ok",
        )
    targets = {
        views.ERRORS: on_problems,
        views.DETAILS: on_instruments,
        views.COLLECTING: on_datasets,
        views.WARNINGS: on_problems,
    }
    milestones = views.coming_up(result)
    with ui.row().classes("lc-pair w-full no-wrap gap-4 items-stretch"):
        with ui.column().classes("lc-grow gap-0").style("flex: 1.6"):
            with panel("Next up"):
                to_do(views.next_up(result), targets)
        if milestones:
            with ui.column().classes("lc-grow gap-0").style("flex: 1"):
                with panel("Coming up"):
                    for milestone in milestones:
                        countdown(milestone)
    charts.overview_section(result)


def banner(result: CatalogResult) -> None:
    found = views.banner(result)
    with ui.element("div").classes("lc-banner w-full"):
        ui.element("img").props(f"src={theme.BANNER} alt=''").classes("lc-banner-art")
        with ui.column().classes("lc-banner-words gap-2"):
            if found.kicker:
                ui.label(found.kicker).classes("lc-banner-kicker")
            ui.label(found.title).classes("lc-banner-title")
            if found.description:
                ui.label(found.description).classes("lc-banner-text")
            with ui.row().classes("lc-banner-facts gap-x-5 gap-y-1"):
                for n, noun in found.facts:
                    with ui.row().classes("items-baseline gap-1 no-wrap"):
                        ui.label(f"{n:,}").classes("lc-banner-number")
                        ui.label(noun)


def to_do(rows: list[views.ToDo], targets: dict[str, Callable[[], None]]) -> None:
    if not rows:
        with ui.row().classes("lc-todo w-full items-center no-wrap gap-3"):
            ui.icon("task_alt").classes("lc-tile-icon lc-ok")
            ui.label("Nothing to do: no problems, every instrument complete")
        return
    for row in rows:
        icon, kind = TODO_LOOK[row.kind]
        with (
            ui.row()
            .classes("lc-todo lc-todo-go w-full items-center no-wrap gap-3")
            .on("click", targets[row.kind])
        ):
            ui.icon(icon).classes(f"lc-tile-icon lc-{kind}")
            with ui.column().classes("grow min-w-0 gap-0"):
                with ui.row().classes("items-baseline gap-1"):
                    ui.label(row.lead).classes("font-semibold")
                    ui.label(row.rest)
                if row.note:
                    ui.label(row.note).classes("lc-note")
                if row.progress is not None:
                    with ui.element("div").classes("lc-todo-bar"):
                        ui.element("div").style(f"width: {row.progress:.0%}")
            ui.icon("chevron_right").classes("lc-tile-go")


def countdown(milestone: views.Milestone) -> None:
    with ui.row().classes("lc-countdown w-full items-baseline no-wrap gap-2"):
        ui.label(f"{milestone.days:,}").classes("lc-countdown-number")
        ui.label("day" if milestone.days == 1 else "days").classes("lc-note")
        ui.space()
        with ui.column().classes("items-end gap-0"):
            ui.label(milestone.name).classes("font-semibold text-right")
            ui.label(
                f"{milestone.study}, {milestone.date}" if milestone.study else str(milestone.date)
            ).classes("lc-note")


def tile(
    label: str,
    value: int,
    icon: str,
    detail: str,
    on_click: Callable[[], None],
    status: str | None = None,
) -> None:
    with ui.column().classes("lc-tile gap-0").on("click", on_click):
        with ui.row().classes("w-full items-center no-wrap gap-3"):
            ui.icon(icon).classes(f"lc-tile-icon lc-{status or 'info'}")
            ui.label(label).classes("lc-tile-label")
            ui.space()
            ui.icon("chevron_right").classes("lc-tile-go")
        ui.label(f"{value:,}").classes("lc-tile-value")
        ui.label(detail).classes("lc-tile-detail")
