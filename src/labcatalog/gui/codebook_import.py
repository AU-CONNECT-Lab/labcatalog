from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import webview
from nicegui import app, run, ui

from labcatalog import defaults
from labcatalog.codebook import core as codebook
from labcatalog.codebook.core import ImportResult
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import problems
from labcatalog.gui.common import col, heading, note, open_path, section, table
from labcatalog.issues import Issue
from labcatalog.pipeline import CatalogResult


@dataclass
class ImportView:
    dataset: str | None = None
    answer: str = ""
    issues: list[Issue] = field(default_factory=list)


def render(
    result: CatalogResult, view: ImportView, on_edit: Callable[[str, int | None], None]
) -> None:
    project = result.project
    names = codebook.unmapped_datasets(project)
    if not names:
        note(
            f"Every dataset already has a column map in {defaults.MAPS_DIR}/. To import a "
            f"codebook for a new data file, add the file under datasets in "
            f"{defaults.CONFIG_FILENAME}, then press Refresh."
        )
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
        selection = await app.native.main_window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=(file_type,)
        )
        if selection:
            await create(Path(selection[0]))

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
            outcome = await run.io_bound(codebook.import_codebook, project, view.dataset)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        view.issues = outcome.issues
        steps.refresh()
        if outcome.written:
            imported_dialog(project.root, outcome)

    def pick(name: str) -> None:
        view.dataset, view.issues = name, []
        steps.refresh()

    @ui.refreshable
    def steps() -> None:
        paths = codebook.codebook_paths(project, view.dataset)
        section("1. Codebook files")
        if not any(path.exists() for path in paths.values()):
            note(
                "labcatalog lists every column of the data file and guesses its instrument "
                "and item from the column name. Given the data dictionary of a REDCap project "
                "(Project Setup, Data Dictionary, Download) or a Qualtrics survey file (Survey, "
                "Tools, Import/Export, Export Survey), it also fills in each item's wording, "
                "options and type, with Qualtrics blocks as instruments. An SPSS file (.sav) of "
                "the same data gives the wording and options from its variable and value labels."
            )
            with ui.row().classes("items-center gap-4 mt-2"):
                ui.button("Create the three files", icon="note_add", on_click=create)
                ui.button(
                    "Create from a REDCap data dictionary",
                    icon="description",
                    on_click=lambda: create_from("CSV files (*.csv)"),
                ).props("outline")
                ui.button(
                    "Create from a Qualtrics survey file",
                    icon="description",
                    on_click=lambda: create_from("Qualtrics survey files (*.qsf)"),
                ).props("outline")
                ui.button(
                    "Create from an SPSS file",
                    icon="description",
                    on_click=lambda: create_from("SPSS data files (*.sav)"),
                ).props("outline")
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
                heading(name)
                table(
                    [col("column", "Column"), col("meaning", "Meaning", sortable=False)],
                    [{"column": c, "meaning": m} for c, m in columns.items()],
                )

        section("2. Fill them in with an AI (optional)")
        note(
            "The prompt holds the format, the data file's column names (no data) and the "
            "instruments already in the project. Paste it into ChatGPT, Claude or your "
            "school's Copilot together with your codebook, then paste the answer here."
        )
        ui.button("Copy AI prompt", icon="content_copy", on_click=copy_prompt).classes("mt-2")
        ui.textarea("The AI's answer").bind_value(view, "answer").props(
            "outlined autogrow"
        ).classes("w-full mt-2")
        ui.button("Replace the three files with this answer", on_click=save_answer).props(
            "flat no-caps"
        )

        section("3. Import")
        note(
            f"Checks the three files, then writes instruments/ and {defaults.MAPS_DIR}/"
            f"{view.dataset}.csv. Instruments already in the project are only mapped."
        )
        ui.button("Check and import", icon="upload", on_click=import_files).classes("mt-2")
        if view.issues:
            problems.issue_table(view.issues, project.root, on_edit).classes("mt-2")

    note(
        "Describe a new data file's columns in three CSV files; labcatalog checks them and "
        "writes the instrument files and the column map."
    )
    ui.select(names, value=view.dataset, label="Dataset", on_change=lambda e: pick(e.value)).props(
        "dense outlined"
    ).classes("w-64 mt-2")
    steps()


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
