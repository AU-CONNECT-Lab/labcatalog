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


def render(result: CatalogResult, selected: str | None, on_select: Callable[[str], None]) -> None:
    summaries = {d.dataset: d for d in result.summary.datasets}
    if not summaries:
        note(f"No datasets yet; add them under datasets in {defaults.CONFIG_FILENAME}.")
        return
    selected = selected if selected in summaries else next(iter(summaries))
    # Spelling out study, wave, reporter and modality lets typing in the box filter by them.
    ui.select(
        {name: dataset_label(result, name) for name in summaries},
        value=selected,
        with_input=True,
        on_change=lambda e: on_select(e.value),
    ).props("dense outlined").classes("w-[36rem]")
    summary = summaries[selected]

    facts(result, summary)

    heading("Instruments")
    table(*completeness_table(result, summary)).classes(remove="w-full")

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
    issues = dataset_issues(result, selected)
    if issues:
        problems.issue_table(issues, result.project.root)
    else:
        note("No problems found.")


def dataset_label(result: CatalogResult, name: str) -> str:
    config = result.project.config
    dataset = dataset_by_name(config, name)
    study = config.studies[dataset.study].label or dataset.study
    return f"{name} ({study}, wave {dataset.wave}, {dataset.reporter}, {dataset.modality})"


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
