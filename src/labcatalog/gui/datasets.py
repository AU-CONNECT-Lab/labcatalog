from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from labcatalog import defaults
from labcatalog.config import dataset_by_name
from labcatalog.gui import problems
from labcatalog.gui.common import col, heading, note, open_path, table, without_line
from labcatalog.issues import Issue
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import DatasetSummary


def render(
    result: CatalogResult,
    selected: str | None,
    on_select: Callable[[str | None], None],
    on_instrument: Callable[[str], None],
) -> None:
    summaries = {d.dataset: d for d in result.summary.datasets}
    if not summaries:
        note(f"No datasets yet; add them under datasets in {defaults.CONFIG_FILENAME}.")
        return
    if selected not in summaries:
        studies(result, summaries, on_select)
        return
    ui.button("All datasets", icon="arrow_back", on_click=lambda: on_select(None)).props(
        "flat dense no-caps"
    )
    detail(result, summaries[selected], on_instrument)


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
        with ui.card().props("flat bordered").classes("w-full mb-4 gap-1"):
            ui.label(study_config.label or study).classes("text-xl font-medium")
            if study_config.description:
                ui.label(study_config.description)
            if study_config.citation or study_config.doi:
                with ui.row().classes("items-baseline gap-2"):
                    ui.label("How to cite").classes("text-grey-7")
                    if study_config.citation:
                        ui.label(study_config.citation)
                    if study_config.doi:
                        ui.link(
                            f"doi:{study_config.doi}",
                            f"https://doi.org/{study_config.doi}",
                            new_tab=True,
                        )
            shown = table(*dataset_table(result, [summaries[n] for n in names])).classes("mt-2")
            shown.classes("cursor-pointer")
            shown.on("rowClick", lambda e: on_select(e.args[1]["name"]))


def dataset_table(
    result: CatalogResult, summaries: list[DatasetSummary]
) -> tuple[list[dict], list[dict]]:
    config = result.project.config
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
                "reporter": dataset.reporter,
                "modality": dataset.modality,
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
    result: CatalogResult, summary: DatasetSummary, on_instrument: Callable[[str], None]
) -> None:
    ui.label(summary.dataset).classes("text-2xl font-medium mt-4")
    facts(result, summary)

    heading("Instruments")
    shown = table(*completeness_table(result, summary)).classes(remove="w-full")
    shown.classes("cursor-pointer")
    shown.on("rowClick", lambda e: on_instrument(e.args[1]["id"]))

    with ui.row().classes("w-full gap-8"):
        with ui.column().classes("gap-1"):
            heading("Missing values")
            table(*missing_table(summary)).classes(remove="w-full")
        if summary.collected_by_month:
            with ui.column().classes("gap-1"):
                heading("Collected by month")
                table(
                    [col("month", "Month"), col("n", "Rows", numeric=True)],
                    [{"month": m, "n": n} for m, n in summary.collected_by_month.items()],
                ).classes(remove="w-full")

    heading("Problems")
    issues = dataset_issues(result, summary.dataset)
    if issues:
        problems.issue_table(issues, result.project.root)
    else:
        note("No problems found.")


def facts(result: CatalogResult, summary: DatasetSummary) -> None:
    config = result.project.config
    dataset = dataset_by_name(config, summary.dataset)
    rows = [
        ("Study", config.studies[dataset.study].label or dataset.study),
        ("Wave", dataset.wave),
        ("Reporter", dataset.reporter),
        ("Modality", dataset.modality),
        ("Rows", summary.n_rows),
        ("IDs", summary.n_ids),
    ]
    if summary.n_groups is not None:
        rows.append((f"{result.summary.group_name.capitalize()} groups", summary.n_groups))
    retention = next(
        r
        for r in result.summary.retention
        if (r.study, r.reporter, r.wave) == (dataset.study, dataset.reporter, dataset.wave)
    )
    if retention.n_from_previous is not None:
        rows.append(("Also in the previous wave", retention.n_from_previous))
        rows.append(("New this wave", retention.n_new))
    if summary.first_date:
        rows.append(("Collected", f"{summary.first_date} to {summary.last_date}"))
    if summary.snapshot_date:
        rows.append(("Data as of", summary.snapshot_date))
    with ui.grid(columns="auto 1fr").classes("gap-x-6 gap-y-1 mt-4 items-baseline"):
        for name, value in rows:
            ui.label(name).classes("text-grey-7")
            ui.label(str(value))
        path = data_path(result, summary.dataset)
        if path:
            ui.label("File").classes("text-grey-7")
            ui.label(path).classes("text-primary cursor-pointer").on(
                "click", lambda: open_path(result.project.root / path)
            )


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
