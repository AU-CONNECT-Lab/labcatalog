from collections.abc import Callable

from nicegui import ui

from labcatalog.gui import charts
from labcatalog.gui.common import card, col, sorted_waves, table, unique
from labcatalog.pipeline import CatalogResult
from labcatalog.reports.participants import wave_dates


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

    with card("Waves", "People and groups with data in each wave"):
        table(*wave_table(result))

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


def wave_table(result: CatalogResult, only: str | None = None) -> tuple[list[dict], list[dict]]:
    config, summary = result.project.config, result.summary
    reporters = unique(r.reporter for r in summary.retention)
    counts = {(r.study, r.wave, r.reporter): r.n for r in summary.retention}
    groups = {(g.study, g.wave): g for g in summary.groups}
    group = summary.group_name
    columns = [
        *([] if only else [col("study", "Study")]),
        col("wave", "Wave"),
        col("dates", "Dates", sortable=False),
        *[col(f"n_{r}", r.capitalize(), numeric=True) for r in reporters],
    ]
    if group:
        columns += [
            col("groups", f"{group.capitalize()} groups", numeric=True),
            col("complete_groups", "With every reporter", numeric=True),
        ]
    rows = []
    for study, study_config in config.studies.items():
        if only and study != only:
            continue
        for wave in sorted_waves(study_config.waves):
            found = groups.get((study, wave))
            rows.append(
                {
                    "study": study_config.label or study,
                    "wave": wave,
                    "dates": wave_dates(study_config.waves[wave]),
                    **{f"n_{r}": counts.get((study, wave, r), "") for r in reporters},
                    "groups": found.groups if found else "",
                    "complete_groups": found.with_every_reporter if found else "",
                }
            )
    return columns, rows
