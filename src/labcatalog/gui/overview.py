from collections.abc import Callable

from nicegui import ui

from labcatalog.config import WaveConfig
from labcatalog.gui import charts
from labcatalog.gui.common import col, heading, sorted_waves, table, unique
from labcatalog.pipeline import CatalogResult


def render(
    result: CatalogResult, on_instruments: Callable[[], None], on_problems: Callable[[], None]
) -> None:
    issues = result.report.issues
    with ui.grid(columns=4).classes("w-full gap-1.5"):
        tile("Instruments", len(result.project.instruments), "moss", on_instruments)
        tile("Datasets", len(result.project.config.datasets), "wheat")
        tile("Errors", sum(i.level == "error" for i in issues), "dusk", on_problems)
        tile("Warnings", sum(i.level == "warning" for i in issues), "amber", on_problems)

    heading("Waves")
    table(*wave_table(result))

    charts.overview_section(result)


def tile(label: str, value: int, look: str, on_click: Callable[[], None] | None = None) -> None:
    box = ui.element("div").classes(f"lc-tile lc-tile-{look}")
    if on_click is not None:
        box.classes("cursor-pointer").on("click", on_click)
    with box:
        ui.label(label).classes("lc-tile-label")
        if on_click is not None:
            ui.icon("north_east").classes("lc-tile-arrow")
        ui.label(str(value)).classes("lc-tile-value")


def wave_table(result: CatalogResult) -> tuple[list[dict], list[dict]]:
    config, summary = result.project.config, result.summary
    reporters = unique(r.reporter for r in summary.retention)
    counts = {(r.study, r.wave, r.reporter): r.n for r in summary.retention}
    groups = {(g.study, g.wave): g for g in summary.groups}
    group = summary.group_name
    columns = [
        col("study", "Study"),
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


def wave_dates(wave: WaveConfig) -> str:
    if wave.start and wave.end:
        return f"{wave.start} to {wave.end}"
    if wave.start:
        return f"since {wave.start}"
    if wave.end:
        return f"until {wave.end}"
    return ""
