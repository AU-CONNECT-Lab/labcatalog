from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from nicegui import ui

from labcatalog.codebook.derivatives import Derived, Request, derive, table_request, table_step
from labcatalog.config import PrepareStep, TableStep
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, note, open_path, panel
from labcatalog.gui.files import choose_path
from labcatalog.metadata import changes
from labcatalog.metadata.scripts import step_change
from labcatalog.paths import expand_path, portable_path
from labcatalog.project import Project, load_config


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
    # Kept as a prepare step, so Run outdated takes the table in again when the pipeline rewrites it.
    keep: bool = True


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


def form_of(table: TableStep, root: Path) -> PipelineForm:
    return PipelineForm(
        table=str(expand_path(table.path, root)),
        name=table.name,
        study=table.study,
        modality=table.modality,
        reporter=table.reporter,
        split=" ".join(table.split),
        columns=" ".join(table.columns),
        wave=table.wave or "",
        label=table.label or "",
    )


def changed(form: PipelineForm, table: TableStep, root: Path) -> bool:
    return request_of(form) != table_request(table, root)


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
        kept = await keep_step(project, request, done) if form.keep else None
        written_dialog(project.root, done, kept)

    with panel(
        "From a pipeline's table",
        help_text="A pipeline's .tsv table and its .json sidecar become instruments, data files "
        "and column maps; running it again keeps your edits.",
    ):
        table_fields(project, form)
        ui.checkbox("Keep as a prepare step").bind_value(form, "keep").tooltip(
            "Run outdated then takes the table in again whenever the pipeline rewrites it"
        )
        ui.button("Write the files", icon="upload", on_click=write).classes("w-fit")


def table_fields(project: Project, form: PipelineForm) -> None:
    config = project.config

    async def choose() -> None:
        found = await choose_path(file_types=("Tables (*.tsv)",), start=project.root)
        if found:
            form.table = str(found)
            chosen.set_text(portable_path(found, project.root).as_posix())

    with ui.row().classes("items-center gap-3"):
        ui.button("Choose table", icon="table_view", on_click=choose).props("flat no-caps").classes(
            "lc-quiet-btn"
        )
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


def field(element: ui.input | ui.select, form: PipelineForm, name: str) -> ui.element:
    # Labels stay above the box, so the placeholders show while it is empty.
    return element.bind_value(form, name).props("dense outlined stack-label")


async def keep_step(project: Project, request: Request, done: Derived) -> str:
    step = table_step(request, project.root, done)
    try:
        taken = {s.name for s in load_config(project.root).prepare}
        change = step_change(project, step.name if step.name in taken else None, step)
        issues = await computed(changes.check, project, [change])
        if issues:
            raise LabCatalogError("; ".join(i.message for i in issues))
        changes.write(project, [change])
    except LabCatalogError as err:
        return f"The prepare step {step.name} was not saved: {err}"
    return (
        f"The prepare step {step.name} takes the table in again: Run outdated in Add data runs it "
        "whenever the pipeline has rewritten the table."
    )


async def taken_again(project: Project, form: PipelineForm) -> tuple[Derived, PrepareStep]:
    # The data files and the step's inputs and outputs follow the table's new settings.
    if absent := missing(form):
        raise LabCatalogError(f"Give {', '.join(absent)} first")
    request = request_of(form)
    done = await computed(derive, project, request)
    return done, table_step(request, project.root, done)


def written_dialog(
    root: Path,
    done: Derived,
    kept: str | None = None,
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> None:
    async def close() -> None:
        dialog.close()
        if on_close is not None:
            await on_close()

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
        elif on_close is None:
            ui.label("Press Refresh to read the new files.")
        note(
            kept
            or "When the pipeline writes the table again, choose it here again: the data files "
            "are rewritten and your changes to the instruments stay."
        )
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=close)
    dialog.open()
