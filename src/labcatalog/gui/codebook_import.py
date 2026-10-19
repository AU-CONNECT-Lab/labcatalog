from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from nicegui import run, ui

from labcatalog import defaults
from labcatalog.codebook import core as codebook
from labcatalog.codebook.core import ImportResult
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import pipeline_table, problems
from labcatalog.gui.common import col, computed, note, open_path, panel, table
from labcatalog.gui.files import choose_path
from labcatalog.issues import Issue
from labcatalog.pipeline import CatalogResult


@dataclass
class ImportView:
    dataset: str | None = None
    answer: str = ""
    issues: list[Issue] = field(default_factory=list)
    pipeline: pipeline_table.PipelineForm = field(default_factory=pipeline_table.PipelineForm)


def render(
    result: CatalogResult, view: ImportView, on_edit: Callable[[str, int | None], None]
) -> None:
    project = result.project
    names = codebook.unmapped_datasets(project)
    if not names:
        pipeline_table.render(project, view.pipeline)
        return
    if view.dataset not in names:
        view.dataset, view.issues = names[0], []

    async def create(dictionary: Path | None = None) -> None:
        try:
            await run.io_bound(codebook.write_templates, project, view.dataset, dictionary)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        steps.refresh()

    async def create_from(file_type: str) -> None:
        chosen = await choose_path(file_types=(file_type,), start=project.root)
        if chosen:
            await create(chosen)

    def copy_prompt() -> None:
        ui.clipboard.write(codebook.ai_prompt(project, view.dataset))
        ui.notify("Prompt copied")

    def save_answer() -> None:
        try:
            codebook.split_ai_answer(project, view.dataset, view.answer)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        view.answer = ""
        ui.notify("Saved the three files; look them over, then import")
        steps.refresh()

    async def import_files() -> None:
        try:
            outcome = await computed(codebook.import_codebook, project, view.dataset)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        view.issues = outcome.issues
        steps.refresh()
        if outcome.written:
            imported_dialog(project.root, outcome)

    async def refreshed() -> None:
        steps.refresh()

    def pick(name: str) -> None:
        view.dataset, view.issues = name, []
        steps.refresh()

    @ui.refreshable
    def steps() -> None:
        paths = codebook.codebook_paths(project, view.dataset)
        with ui.row().classes("w-full items-center gap-2"):
            ui.label("1. Codebook files").classes("lc-subhead")
            ui.space()
            kept_menu(project, view.dataset, refreshed)
        if not any(path.exists() for path in paths.values()):
            note(
                "labcatalog guesses each column's item from its name; a REDCap dictionary, Qualtrics survey file or SPSS file also gives the wording and options."
            )
            with ui.row().classes("items-center gap-2 mt-1"):
                ui.button("Create the three files", icon="note_add", on_click=create)
                ui.button(
                    "Create from a REDCap data dictionary",
                    icon="description",
                    on_click=lambda: create_from("CSV files (*.csv)"),
                ).props("flat no-caps").classes("lc-quiet-btn")
                ui.button(
                    "Create from a Qualtrics survey file",
                    icon="description",
                    on_click=lambda: create_from("Qualtrics survey files (*.qsf)"),
                ).props("flat no-caps").classes("lc-quiet-btn")
                ui.button(
                    "Create from an SPSS file",
                    icon="description",
                    on_click=lambda: create_from("SPSS data files (*.sav)"),
                ).props("flat no-caps").classes("lc-quiet-btn")
            return
        with ui.row().classes("items-center gap-4 mt-2"):
            for path in paths.values():
                file_link(project.root, path)
            ui.button(
                "Open folder",
                icon="folder_open",
                on_click=lambda: open_path(paths[codebook.ITEMS].parent),
            ).props("flat dense no-caps")
        note(
            "Edit them in Excel or any editor and save as CSV UTF-8, or fill them in with an AI below."
        )
        with ui.expansion("What goes in each column").classes("w-full"):
            for name, columns in codebook.COLUMNS.items():
                ui.label(name).classes("lc-subhead")
                table(
                    [col("column", "Column"), col("meaning", "Meaning", sortable=False)],
                    [{"column": c, "meaning": m} for c, m in columns.items()],
                )

        ui.label("2. Fill them in with an AI (optional)").classes("lc-subhead")
        note(
            "The prompt holds the format, the data file's column names (no data) and the "
            "instruments already in the project. Paste it into ChatGPT, Claude or your "
            "school's Copilot together with your codebook, then paste the answer here."
        )
        ui.button("Copy AI prompt", icon="content_copy", on_click=copy_prompt).props(
            "flat no-caps"
        ).classes("lc-quiet-btn w-fit")
        ui.textarea("The AI's answer").bind_value(view, "answer").props("outlined").classes(
            "lc-grow w-full mt-2"
        )
        ui.button("Replace the three files with this answer", on_click=save_answer).props(
            "flat no-caps"
        )

        ui.label("3. Import").classes("lc-subhead")
        note(
            f"Checks the three files, then writes instruments/ and {defaults.MAPS_DIR}/"
            f"{view.dataset}.csv. Instruments already in the project are only mapped."
        )
        ui.button("Check and import", icon="upload", on_click=import_files).classes("w-fit")
        if view.issues:
            problems.issue_table(view.issues, project.root, on_edit)

    with panel("Files without a column map", help_text=INTRO) as tools:
        steps()
    with tools:
        ui.select(
            names, value=view.dataset, label="Dataset", on_change=lambda e: pick(e.value)
        ).props("dense outlined").classes("w-64")
    pipeline_table.render(project, view.pipeline)


INTRO = (
    "Data files listed in labcatalog.yaml whose columns are not linked yet: describe them in "
    "three CSV files, and labcatalog writes the column map and any new instruments."
)


def file_link(root: Path, path: Path) -> None:
    ui.label(path.relative_to(root).as_posix()).classes("text-primary cursor-pointer").on(
        "click", lambda: open_path(path)
    )


def imported_dialog(root: Path, outcome: ImportResult) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full"):
        ui.label("Imported").classes("text-xl font-medium")
        with ui.column().classes("gap-1"):
            for path in outcome.written:
                file_link(root, path)
        if outcome.reused:
            note(f"Already in the project, so only mapped: {', '.join(outcome.reused)}")
        if outcome.steps:
            ui.label(
                "One more step: labcatalog does not edit your study files, so add these "
                "lines yourself, then press Refresh."
            )
            for instruction, lines in outcome.steps:
                ui.label(instruction)
                ui.code(lines, language="yaml").classes("w-full")
        else:
            ui.label("Press Refresh to see the new instruments.")
        with ui.row().classes("w-full justify-end"):
            ui.button(
                "Open studies folder",
                icon="folder_open",
                on_click=lambda: open_path(root / defaults.STUDIES_DIR),
            ).props("flat no-caps")
            ui.button("Close", on_click=dialog.close)
    dialog.open()


def kept_menu(project, dataset: str, on_changed: Callable[[], Awaitable[None]]) -> None:
    # The codebook as the lab got it, kept in the project to look up while describing the data.
    kept = codebook.kept_sources(project, dataset)

    async def add() -> None:
        chosen = await choose_path(start=project.root)
        if chosen is None:
            return
        await run.io_bound(codebook.keep_source, project, dataset, chosen)
        folder = codebook.source_folder(project, dataset).relative_to(project.root).as_posix()
        ui.notify(f"Kept {chosen.name} in {folder}")
        await on_changed()

    label = "Codebook" if kept else "Keep the codebook"
    with (
        ui.dropdown_button(label, icon="menu_book", auto_close=True)
        .props("flat dense no-caps")
        .tooltip("The codebook as you got it, such as a PDF or a data dictionary")
    ):
        for path in kept:
            ui.item(path.name, on_click=partial(open_path, path))
        ui.item("Add a file", on_click=add)
