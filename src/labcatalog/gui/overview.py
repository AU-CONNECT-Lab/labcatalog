from collections.abc import Callable

from nicegui import ui

from labcatalog.gui import charts
from labcatalog.gui.common import block, sorted_waves, unique
from labcatalog.pipeline import CatalogResult


def render(
    result: CatalogResult, on_instruments: Callable[[], None], on_problems: Callable[[], None]
) -> None:
    config = result.project.config
    issues = result.report.issues
    errors = sum(i.level == "error" for i in issues)
    warnings = sum(i.level == "warning" for i in issues)
    with block("Summary"), ui.grid(columns=2).classes("w-full gap-x-14 gap-y-0"):
        with facts():
            fact("Instruments", str(len(result.project.instruments)), on_click=on_instruments)
            fact("Datasets", str(len(config.datasets)))
            fact("Studies", ", ".join(s.label or name for name, s in config.studies.items()))
        with facts():
            fact("Waves", ", ".join(sorted_waves(d.wave for d in config.datasets)))
            fact("Reporters", ", ".join(unique(d.reporter for d in config.datasets)))
            fact("Errors", str(errors), "bad" if errors else "ok", on_problems)
            fact("Warnings", str(warnings), "warn" if warnings else "ok", on_problems)

    charts.overview_section(result)


def facts() -> ui.grid:
    return ui.grid(columns="11rem 1fr").classes("lc-facts gap-0")


def fact(
    label: str,
    value: str,
    status: str | None = None,
    on_click: Callable[[], None] | None = None,
) -> None:
    ui.label(label).classes("lc-fact-key")
    with ui.element("div"):
        shown = ui.label(value).classes(f"lc-pill lc-{status}" if status else "inline")
        if on_click is not None:
            shown.classes("lc-link").on("click", on_click)
