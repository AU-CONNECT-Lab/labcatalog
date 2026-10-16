from collections.abc import Callable

from nicegui import ui

from labcatalog.gui import charts
from labcatalog.pipeline import CatalogResult


def render(
    result: CatalogResult, on_instruments: Callable[[], None], on_problems: Callable[[], None]
) -> None:
    issues = result.report.issues
    errors = sum(i.level == "error" for i in issues)
    warnings = sum(i.level == "warning" for i in issues)
    with ui.grid(columns=4).classes("w-full gap-4"):
        kpi("Instruments", len(result.project.instruments), on_click=on_instruments)
        kpi("Datasets", len(result.project.config.datasets))
        kpi("Errors", errors, "bad" if errors else None, on_problems)
        kpi("Warnings", warnings, "warn" if warnings else None, on_problems)

    charts.overview_section(result)


def kpi(
    label: str,
    value: int,
    status: str | None = None,
    on_click: Callable[[], None] | None = None,
) -> None:
    box = ui.card().props("flat").classes("lc-card lc-kpi")
    if on_click is not None:
        box.classes("cursor-pointer").on("click", on_click)
    with box:
        with ui.row().classes("items-center gap-2"):
            if status is not None:
                ui.element("span").classes(f"lc-dot lc-dot-{status}")
            ui.label(label).classes("lc-kpi-label")
        if on_click is not None:
            ui.icon("north_east").classes("lc-kpi-arrow")
        ui.label(str(value)).classes("lc-kpi-value")
