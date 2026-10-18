from dataclasses import dataclass
from pathlib import Path

import webview
from nicegui import app, ui

from labcatalog.codebook.derivatives import Derived, Request, command_line, derive
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, note, open_path, panel
from labcatalog.paths import portable_path
from labcatalog.project import Project


@dataclass
class PipelineForm:
    table: str = ""
    name: str = ""
    study: str | None = None
    modality: str | None = None
    reporter: str | None = None
    split: str = ""
    columns: str = ""
    wave: str = ""
    label: str = ""


def words(text: str) -> list[str]:
    return [w for w in text.replace(",", " ").split() if w]


def request_of(form: PipelineForm) -> Request:
    return Request(
        Path(form.table),
        form.name.strip(),
        form.study or "",
        form.modality or "",
        form.reporter or "",
        words(form.split),
        words(form.columns),
        form.wave.strip() or None,
        form.label.strip() or None,
    )


def missing(form: PipelineForm) -> list[str]:
    fields = {
        "a table": form.table,
        "a name": form.name.strip(),
        "the study": form.study,
        "the modality": form.modality,
        "the reporter": form.reporter,
    }
    return [label for label, value in fields.items() if not value]


def render(project: Project, form: PipelineForm) -> None:
    config = project.config
    form.study = form.study or next(iter(config.studies), None)

    async def choose() -> None:
        selection = await app.native.main_window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=("Tables (*.tsv)",)
        )
        if selection:
            form.table = selection[0]
            chosen.set_text(portable_path(Path(form.table), project.root).as_posix())

    async def write() -> None:
        if absent := missing(form):
            ui.notify(f"Give {', '.join(absent)} first", type="warning")
            return
        request = request_of(form)
        try:
            done = await computed(derive, project, request)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        written_dialog(project.root, done, command_line(request, project.root))

    with panel(
        "From a pipeline's table",
        "A pipeline's table of measures, a .tsv with a bids_name or participant_id column and "
        "a .json sidecar of the same name, becomes one instrument per value of Split by, and a "
        "data file and a column map for each wave. Running it again keeps your edits to the "
        "instruments.",
    ):
        with ui.row().classes("items-center gap-3"):
            ui.button("Choose table", icon="table_view", on_click=choose).props(
                "flat no-caps"
            ).classes("lc-quiet-btn")
            chosen = ui.label(
                portable_path(Path(form.table), project.root).as_posix()
                if form.table
                else "No table chosen"
            ).classes("lc-note")
        with ui.element("div").classes("lc-form w-full"):
            field(ui.input("Name", placeholder="fnirs_qc"), form, "name")
            field(ui.select(list(config.studies), label="Study"), form, "study")
            field(ui.select(config.vocab.modalities, label="Modality"), form, "modality")
            field(ui.select(config.vocab.reporters, label="Reporter"), form, "reporter")
            field(ui.input("Split by", placeholder="task"), form, "split").tooltip(
                "Entities whose values become separate instruments"
            )
            field(ui.input("Columns", placeholder="raw_* motion_*"), form, "columns").tooltip(
                "Patterns of the columns to take; every column of numbers or with Levels if empty"
            )
            field(ui.input("Wave", placeholder="from ses-"), form, "wave").tooltip(
                "Only for a table without sessions"
            )
            field(ui.input("Instrument name", placeholder="the Name"), form, "label")
        ui.button("Write the files", icon="upload", on_click=write).classes("w-fit")


def field(element: ui.input | ui.select, form: PipelineForm, name: str) -> ui.element:
    # Labels stay above the box, so the placeholders show while it is empty.
    return element.bind_value(form, name).props("dense outlined stack-label")


def written_dialog(root: Path, done: Derived, command: str) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[48rem] max-w-full"):
        ui.label("Written").classes("text-xl font-medium")
        with ui.column().classes("gap-1"):
            for path in done.written:
                ui.label(portable_path(path, root).as_posix()).classes(
                    "text-primary cursor-pointer"
                ).on("click", lambda p=path: open_path(p))
        if done.left_out:
            note(f"Neither numbers nor given Levels, so left out: {', '.join(done.left_out)}")
        if done.steps:
            ui.label(
                "labcatalog does not edit labcatalog.yaml or the study files, so add these "
                "lines yourself, then press Refresh."
            )
            for instruction, lines in done.steps:
                ui.label(instruction)
                ui.code(lines, language="yaml").classes("w-full")
        else:
            ui.label("Press Refresh to read the new files.")
        ui.label("To run it again whenever the pipeline does, add it as a prepare step:")
        ui.code(command, language="bash").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=dialog.close)
    dialog.open()
