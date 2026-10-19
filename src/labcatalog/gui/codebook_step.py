from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from nicegui import run, ui

from labcatalog import defaults
from labcatalog.codebook import core as codebook
from labcatalog.codebook.core import ImportResult
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import codebook_import, problems
from labcatalog.gui.common import col, computed, folding_panel, note, open_path, table
from labcatalog.gui.files import choose_path
from labcatalog.issues import Issue
from labcatalog.metadata import editing
from labcatalog.project import Project

DICTIONARIES = {
    "Create from a REDCap data dictionary": "CSV files (*.csv)",
    "Create from a Qualtrics survey file": "Qualtrics survey files (*.qsf)",
    "Create from an SPSS file": "SPSS data files (*.sav)",
}


@dataclass
class CodebookView:
    answer: str = ""
    issues: list[Issue] = field(default_factory=list)


def drafts(root: Path) -> list[str]:
    return editing.editable_files(root)["Drafts"]


def render(
    project: Project,
    view: CodebookView,
    on_edit: Callable[[str, int | None], None],
    reload: Callable[[], Awaitable[None]],
) -> None:
    root = project.root
    paths = codebook.codebook_paths(project, codebook.NEW)

    async def create(dictionary: Path | None = None) -> None:
        try:
            await run.io_bound(codebook.write_new_templates, project, dictionary)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        steps.refresh()

    async def create_from(file_type: str) -> None:
        chosen = await choose_path(file_types=(file_type,), start=root)
        if chosen:
            await create(chosen)

    def copy_prompt() -> None:
        ui.clipboard.write(codebook.new_prompt(project))
        ui.notify("Prompt copied")

    def save_answer() -> None:
        try:
            codebook.split_ai_answer(project, codebook.NEW, view.answer)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        view.answer = ""
        ui.notify("Saved the three files; look them over, then import")
        steps.refresh()

    async def import_files() -> None:
        try:
            outcome = await computed(codebook.import_instruments, project)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        view.issues = outcome.issues
        if outcome.written:
            imported_dialog(root, outcome)
            await reload()
        else:
            steps.refresh()

    async def refreshed() -> None:
        steps.refresh()

    @ui.refreshable
    def steps() -> None:
        with ui.row().classes("w-full items-center gap-2"):
            ui.label("1. Codebook files").classes("lc-subhead")
            ui.space()
            codebook_import.kept_menu(project, codebook.NEW, refreshed)
        if not any(path.exists() for path in paths.values()):
            note(
                "Start from a REDCap dictionary, a Qualtrics survey file or an SPSS file, or from empty files to fill in; no data needed yet."
            )
            with ui.row().classes("items-center gap-2 mt-1"):
                ui.button("Create empty files", icon="note_add", on_click=lambda: create())
                for label, file_type in DICTIONARIES.items():
                    ui.button(
                        label, icon="description", on_click=lambda t=file_type: create_from(t)
                    ).props("flat no-caps").classes("lc-quiet-btn")
            return
        with ui.row().classes("items-center gap-4 mt-2"):
            for path in paths.values():
                codebook_import.file_link(root, path)
            ui.button(
                "Open folder",
                icon="folder_open",
                on_click=lambda: open_path(paths[codebook.ITEMS].parent),
            ).props("flat dense no-caps")
        with ui.expansion("What goes in each column").classes("w-full"):
            for name, columns in codebook.COLUMNS.items():
                if name == codebook.ITEMS:
                    columns = {**columns, "column": codebook.NEW_COLUMN}
                ui.label(name).classes("lc-subhead")
                table(
                    [col("column", "Column"), col("meaning", "Meaning", sortable=False)],
                    [{"column": c, "meaning": m} for c, m in columns.items()],
                )

        ui.label("2. Fill them in with an AI (optional)").classes("lc-subhead")
        note(
            "The prompt holds the format, what the files hold so far and the instruments already "
            "in the project. Paste it into ChatGPT, Claude or your school's Copilot together with "
            "your codebook, then paste the answer here."
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
            "Checks the three files, then writes one file in instruments/ for each new "
            f"instrument, and moves the three files aside to {defaults.CODEBOOK_DIR}/"
            f"{codebook.NEW}_<date>/ so the next codebook starts from empty ones."
        )
        ui.button("Check and import", icon="upload", on_click=import_files).classes("w-fit")
        if view.issues:
            problems.issue_table(view.issues, root, on_edit)

    # Folded unless a codebook is under way, so the editor below is what the step opens on.
    begun = any(path.exists() for path in paths.values()) or bool(view.issues)
    with folding_panel(
        "From a codebook", "New instruments from a data dictionary or any codebook", begun
    ):
        steps()


def imported_dialog(root: Path, outcome: ImportResult) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label("Imported").classes("text-xl font-medium")
        with ui.column().classes("gap-1"):
            for path in outcome.written:
                codebook_import.file_link(root, path)
        note(
            "Check each instrument in the editor below. Then Add data links a data file's columns to "
            "their items."
        )
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=dialog.close)
    dialog.open()
