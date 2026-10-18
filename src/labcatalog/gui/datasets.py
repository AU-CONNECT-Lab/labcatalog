from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import ui

from labcatalog import defaults
from labcatalog.charts import views
from labcatalog.config import dataset_by_name
from labcatalog.gui import datalad, id_fix, new_dataset, problems
from labcatalog.gui.common import (
    code_tabs,
    col,
    empty,
    open_path,
    page_head,
    panel,
    table,
    without_line,
)
from labcatalog.gui.database import database_button
from labcatalog.issues import Issue
from labcatalog.pipeline import CatalogResult
from labcatalog.stats.summary import DatasetSummary


def render(
    result: CatalogResult,
    selected: str | None,
    on_select: Callable[[str | None], None],
    on_instrument: Callable[[str], None],
    on_frozen: Callable[[], Awaitable[None]],
    on_open_freeze: Callable[[str], Awaitable[None]] | None,
    on_edit: Callable[[str, int | None], None],
    on_added: Callable[[str], Awaitable[None]],
) -> None:
    summaries = {d.dataset: d for d in result.summary.datasets}
    if selected not in summaries:
        with page_head("Datasets", list_summary(result, summaries)):
            if result.project.config.studies:
                ui.button(
                    "Add a dataset",
                    icon="add",
                    on_click=lambda: new_dataset.open_wizard(result, on_added),
                ).props("flat no-caps").classes("lc-quiet-btn")
            if summaries:
                database_button(result)
                datalad.freeze_button(result, on_frozen)
        if not summaries:
            empty("No datasets yet; press Add a dataset, after adding a study on the Studies page.")
            return
        studies(result, summaries, on_select)
        datalad.freezes_table(result.project.root, on_open_freeze)
        return
    with ui.row().classes("items-center gap-1 no-wrap"):
        ui.button("Datasets", icon="arrow_back", on_click=lambda: on_select(None)).props(
            "flat dense no-caps"
        )
        ui.icon("chevron_right").classes("lc-crumb-sep")
        ui.label(selected).classes("lc-crumb")
    detail(result, summaries[selected], on_instrument, on_edit, on_frozen)


def list_summary(result: CatalogResult, summaries: dict[str, DatasetSummary]) -> str:
    studies = {d.study for d in result.project.config.datasets if d.name in summaries}
    rows = sum(s.n_rows for s in summaries.values())
    kind = "study" if len(studies) == 1 else "studies"
    return f"{len(summaries)} datasets in {len(studies)} {kind}, {rows:,} rows"


def studies(
    result: CatalogResult,
    summaries: dict[str, DatasetSummary],
    on_select: Callable[[str | None], None],
) -> None:
    config = result.project.config
    for study, study_config in config.studies.items():
        names = [d.name for d in config.datasets if d.study == study and d.name in summaries]
        if not names:
            continue
        with panel(study_config.label or study, f"{len(names)} datasets; click one to open it"):
            shown = table(*dataset_table(result, [summaries[n] for n in names]))
            shown.classes("cursor-pointer")
            shown.add_slot("body-cell-wave", WAVE_CELL)
            shown.add_slot("body-cell-modality", MODALITY_CELL)
            shown.on("rowClick", lambda e: on_select(e.args[1]["name"]))


WAVE_CELL = r"""
<q-td :props="props">
  <span class="row inline items-center no-wrap q-gutter-x-sm">
    <span class="lc-dot" :style="{background: props.row.wave_color}"></span>
    <span>{{ props.value }}</span>
  </span>
</q-td>
"""
MODALITY_CELL = r"""
<q-td :props="props"><span class="lc-pill lc-info">{{ props.value }}</span></q-td>
"""


def methods_of(result: CatalogResult, study: str) -> dict[str, str]:
    return {
        modality: text
        for content in result.project.studies.values()
        if content.study == study
        for modality, text in content.methods.items()
    }


def paragraphs(text: str) -> None:
    # Keeps the blank lines between paragraphs that YAML block text carries.
    ui.label(text.strip()).style("white-space: pre-line").classes("lc-prose")


def dataset_table(
    result: CatalogResult, summaries: list[DatasetSummary]
) -> tuple[list[dict], list[dict]]:
    config = result.project.config
    colors = views.wave_colors(result)
    columns = [
        col("name", "Dataset"),
        col("wave", "Wave"),
        col("reporter", "Reporter"),
        col("modality", "Modality"),
        col("n_rows", "Rows", numeric=True),
        col("n_ids", "IDs", numeric=True),
        col("collected", "Collected", sortable=False),
        col("snapshot", "Data as of"),
    ]
    rows = []
    for summary in summaries:
        dataset = dataset_by_name(config, summary.dataset)
        rows.append(
            {
                "name": summary.dataset,
                "wave": dataset.wave,
                "wave_color": colors.get(dataset.wave, ""),
                "reporter": dataset.reporter,
                "modality": config.vocab.modality_label(dataset.modality),
                "n_rows": summary.n_rows,
                "n_ids": summary.n_ids,
                "collected": f"{summary.first_date} to {summary.last_date}"
                if summary.first_date
                else "",
                "snapshot": str(summary.snapshot_date or ""),
            }
        )
    return columns, rows


def detail(
    result: CatalogResult,
    summary: DatasetSummary,
    on_instrument: Callable[[str], None],
    on_edit: Callable[[str, int | None], None],
    on_changed: Callable[[], Awaitable[None]],
) -> None:
    facts(result, summary, on_changed)
    with ui.row().classes("w-full no-wrap items-start gap-4"):
        with ui.column().classes("grow min-w-0 gap-4"):
            with panel("Instruments", "People who answered all, some or none of the items"):
                shown = table(*completeness_table(result, summary))
                shown.classes("cursor-pointer")
                shown.on("rowClick", lambda e: on_instrument(e.args[1]["id"]))
            main_panels(result, summary, on_edit)
        with ui.column().classes("w-80 shrink-0 gap-4"):
            with panel("Missing values", "Cells of each kind"):
                table(*missing_table(summary))
            if summary.collected_by_month:
                with panel("Collected by month"):
                    table(
                        [col("month", "Month"), col("n", "Rows", numeric=True)],
                        [{"month": m, "n": n} for m, n in summary.collected_by_month.items()],
                    )


def main_panels(
    result: CatalogResult,
    summary: DatasetSummary,
    on_edit: Callable[[str, int | None], None],
) -> None:
    dataset = dataset_by_name(result.project.config, summary.dataset)
    methods = methods_of(result, dataset.study).get(dataset.modality)
    if methods:
        with panel("Methods"):
            paragraphs(methods)

    issues = dataset_issues(result, summary.dataset)
    with panel("Problems", "In this dataset's file and column map"):
        if issues:
            problems.issue_table(issues, result.project.root, on_edit)
        else:
            empty("No problems found.", "check_circle")

    label_code(result.label_snippets[summary.dataset])


def label_code(snippets: dict[str, str]) -> None:
    with panel(
        "Label code",
        "Puts the item wording, response labels and missing codes on the data: R with the "
        "haven package, Python as the dictionaries pyreadstat takes to save a .sav file.",
    ):
        code_tabs(snippets)


def facts(
    result: CatalogResult, summary: DatasetSummary, on_changed: Callable[[], Awaitable[None]]
) -> None:
    config = result.project.config
    dataset = dataset_by_name(config, summary.dataset)
    rows = [
        ("Study", config.studies[dataset.study].label or dataset.study),
        ("Wave", dataset.wave),
        ("Reporter", dataset.reporter),
        ("Modality", config.vocab.modality_label(dataset.modality)),
        ("Rows", summary.n_rows),
        ("IDs", summary.n_ids),
    ]
    if summary.n_groups is not None:
        rows.append((f"{result.summary.group_name.capitalize()} groups", summary.n_groups))
    # Against the last wave with this modality, so a scan every other wave counts its own people.
    counted = next(
        m
        for m in result.summary.modalities
        if (m.study, m.reporter, m.wave, m.modality)
        == (dataset.study, dataset.reporter, dataset.wave, dataset.modality)
    )
    if counted.previous_wave is not None:
        rows.append((f"Also at Wave {counted.previous_wave}", counted.n_from_previous))
        rows.append((f"New since Wave {counted.previous_wave}", counted.n_new))
    if summary.first_date:
        rows.append(("Collected", f"{summary.first_date} to {summary.last_date}"))
    if summary.snapshot_date:
        rows.append(("Data as of", summary.snapshot_date))
    path = data_path(result, summary.dataset)
    with ui.column().classes("lc-panel lc-summary w-full gap-3"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.label(summary.dataset).classes("lc-summary-title")
            ui.label(config.vocab.modality_label(dataset.modality)).classes("lc-pill lc-info")
            ui.space()
            if summary.dataset in result.datasets:
                ui.button(
                    "Fix IDs",
                    icon="badge",
                    on_click=lambda: id_fix.open_dialog(result, summary.dataset, on_changed),
                ).props("flat dense no-caps").tooltip("Correct IDs by rules or by hand")
            if path:
                ui.button(
                    path, icon="open_in_new", on_click=lambda: open_path(result.project.root / path)
                ).props("flat dense no-caps").tooltip("Open in its own app")
        with ui.element("div").classes("lc-stats w-full"):
            for name, value in rows:
                with ui.column().classes("gap-0"):
                    ui.label(name).classes("lc-fact-key")
                    shown = f"{value:,}" if isinstance(value, int) else str(value)
                    ui.label(shown).classes("lc-stat")


def data_path(result: CatalogResult, dataset: str) -> str | None:
    return next((f.path for f in result.manifest.files if f.dataset == dataset), None)


def dataset_issues(result: CatalogResult, dataset: str) -> list[Issue]:
    data = data_path(result, dataset)
    variable_map = Path(defaults.MAPS_DIR, f"{dataset}.csv").as_posix()
    return [
        issue
        for issue in result.report.issues
        if issue.location
        and (issue.location == data or without_line(issue.location) == variable_map)
    ]


def completeness_table(
    result: CatalogResult, summary: DatasetSummary
) -> tuple[list[dict], list[dict]]:
    instruments = result.project.instruments
    columns = [
        col("instrument", "Instrument"),
        col("n_items", "Items", numeric=True),
        col("complete", "Answered all", numeric=True),
        col("partial", "Some", numeric=True),
        col("empty", "None", numeric=True),
    ]
    rows = [
        {
            "id": c.instrument_id,
            "instrument": instruments[c.instrument_id].abbreviation or c.instrument_id,
            "n_items": c.n_items,
            "complete": c.complete,
            "partial": c.partial,
            "empty": c.empty,
        }
        for c in summary.completeness
    ]
    return columns, rows


def missing_table(summary: DatasetSummary) -> tuple[list[dict], list[dict]]:
    rows = [{"label": label, "n": n} for label, n in summary.missing_totals.items()]
    rows.append({"label": "not a response option", "n": summary.n_unexpected})
    return [col("label", "Kind"), col("n", "Cells", numeric=True)], rows
