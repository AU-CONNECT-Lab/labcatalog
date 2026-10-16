from collections.abc import Callable

from nicegui import ui

from labcatalog.gui import charts
from labcatalog.gui.common import sorted_waves, unique
from labcatalog.metadata.completeness import gaps
from labcatalog.pipeline import CatalogResult


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
    with ui.grid(columns=4).classes("w-full gap-4"):
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

    charts.overview_section(result)


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
