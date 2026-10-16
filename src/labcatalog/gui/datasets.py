from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import run, ui

from labcatalog import defaults
from labcatalog.config import dataset_by_name
from labcatalog.datalad.freeze import RECORD_ONLY, datalad_datasets, list_freezes
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences, problems
from labcatalog.gui.common import cited, col, heading, note, open_path, table, without_line
from labcatalog.issues import Issue
from labcatalog.paths import portable_path
from labcatalog.pipeline import CatalogResult, run_freeze
from labcatalog.stats import DatasetSummary


def render(
    result: CatalogResult,
    selected: str | None,
    on_select: Callable[[str | None], None],
    on_instrument: Callable[[str], None],
    on_frozen: Callable[[], Awaitable[None]],
    on_open_freeze: Callable[[str], Awaitable[None]] | None,
) -> None:
    summaries = {d.dataset: d for d in result.summary.datasets}
    if not summaries:
        note(f"No datasets yet; add them under datasets in {defaults.CONFIG_FILENAME}.")
        return
    if selected not in summaries:
        freeze_button(result, on_frozen)
        studies(result, summaries, on_select)
        freezes_table(result.project.root, on_open_freeze)
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
            if study_config.reference:
                with ui.row().classes("items-baseline gap-2"):
                    ui.label("How to cite").classes("text-grey-7")
                    cited(result.project.bibliography, study_config.reference)
            shown = table(*dataset_table(result, [summaries[n] for n in names])).classes("mt-2")
            shown.classes("cursor-pointer")
            shown.on("rowClick", lambda e: on_select(e.args[1]["name"]))


def freeze_button(result: CatalogResult, on_frozen: Callable[[], Awaitable[None]]) -> None:
    root = result.project.root
    tagged = [
        "the project folder" if p == root else portable_path(p, root).as_posix()
        for p in datalad_datasets(result.project)
    ]

    def open_dialog() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
            ui.label("Freeze the data").classes("text-lg font-medium")
            note(
                "A freeze writes a record of every data file labcatalog reads (checksum, rows, "
                f"participants) to {defaults.FREEZES_DIR}, so you can say later which data a "
                "result used."
            )
            if tagged:
                note(
                    "The data are in DataLad, so the freeze also saves these datasets and tags "
                    f"them with its name, which lets you get this version back: {', '.join(tagged)}."
                )
            else:
                note(RECORD_ONLY)
            name = (
                ui.input("Name", placeholder="2026-06-submission")
                .props("outlined dense autofocus")
                .classes("w-full")
            )
            status = ui.label().classes("lc-note")

            async def go() -> None:
                datalad = preferences.load().get(preferences.DATALAD)
                status.set_text("Freezing")
                try:
                    path, record = await run.io_bound(
                        run_freeze, root, (name.value or "").strip(), datalad
                    )
                except LabCatalogError as err:
                    status.set_text(str(err))
                    return
                dialog.close()
                done = f"Froze {record.name} in {portable_path(path, root).as_posix()}"
                if record.tag:
                    done += f" and tagged {len(record.manifest.datalad)} DataLad dataset(s)"
                ui.notify(done)
                await on_frozen()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Freeze", on_click=go)
        dialog.open()

    with ui.row().classes("w-full justify-end"):
        ui.button("Freeze", icon="ac_unit", on_click=open_dialog).props("flat no-caps")


# Only a freeze with a DataLad tag has its data to open.
OPEN_CELL = r"""
<q-td :props="props">
  <q-btn v-if="props.row.tagged" flat dense no-caps color="primary" label="Open"
         @click="$parent.$emit('open_freeze', props.row)" />
</q-td>
"""


def freezes_table(root: Path, on_open: Callable[[str], Awaitable[None]] | None) -> None:
    found = list_freezes(root)
    if not found:
        return
    heading("Freezes")
    columns = [
        col("frozen", "Frozen"),
        col("name", "Name"),
        col("tag", "DataLad tag"),
        col("files", "Data files", numeric=True),
    ]
    if on_open:
        columns.append(col("open", "", sortable=False))
    rows = [
        {
            "frozen": f.frozen_at.strftime("%Y-%m-%d %H:%M"),
            "name": f.name,
            "tag": f.tag or "none, record only",
            "files": len(f.manifest.files),
            "tagged": f.tag is not None,
        }
        for f in found
    ]
    shown = table(columns, rows).classes(remove="w-full")
    if on_open:
        shown.add_slot("body-cell-open", OPEN_CELL)
        shown.on("open_freeze", lambda e: on_open(e.args["name"]))


def methods_of(result: CatalogResult, study: str) -> dict[str, str]:
    return {
        modality: text
        for content in result.project.studies.values()
        if content.study == study
        for modality, text in content.methods.items()
    }


def paragraphs(text: str) -> None:
    # Keeps the blank lines between paragraphs that YAML block text carries.
    ui.label(text.strip()).style("white-space: pre-line").classes("max-w-4xl")


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
    dataset = dataset_by_name(result.project.config, summary.dataset)
    methods = methods_of(result, dataset.study).get(dataset.modality)
    if methods:
        heading("Methods")
        paragraphs(methods)

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

    label_code(result.label_snippets[summary.dataset])


def label_code(snippets: dict[str, str]) -> None:
    heading("Label code")
    note(
        "Puts the item wording, response labels and missing codes on the data: R with the "
        "haven package, Python as the dictionaries pyreadstat takes to save a .sav file."
    )
    with ui.tabs().props("dense no-caps align=left") as tabs:
        ui.tab("r", label="R")
        ui.tab("python", label="Python")
    with ui.tab_panels(tabs, value="r").classes("w-full"):
        with ui.tab_panel("r").classes("p-0"):
            ui.code(snippets["r"], language="r").classes("w-full")
        with ui.tab_panel("python").classes("p-0"):
            ui.code(snippets["python"], language="python").classes("w-full")


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
