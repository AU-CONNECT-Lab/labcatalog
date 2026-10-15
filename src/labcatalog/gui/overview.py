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
    with ui.row().classes("gap-4"):
        stat("Instruments", len(result.project.instruments), on_instruments)
        stat("Datasets", len(result.project.config.datasets))
        stat("Errors", sum(i.level == "error" for i in issues), on_problems)
        stat("Warnings", sum(i.level == "warning" for i in issues), on_problems)

    heading("Waves")
    table(*wave_table(result))

    charts.overview_section(result)


def stat(label: str, value: int, on_click: Callable[[], None] | None = None) -> None:
    card = ui.card().classes("min-w-32 px-4 py-2 gap-0")
    if on_click is not None:
        card.classes("cursor-pointer").on("click", on_click)
    with card:
        ui.label(str(value)).classes("text-2xl font-medium")
        ui.label(label).classes("text-grey-7")


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
