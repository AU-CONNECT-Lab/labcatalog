from pathlib import Path

import webview
from nicegui import app, run, ui

from labcatalog import __version__
from labcatalog.exceptions import LabCatalogError
from labcatalog.issues import summarize_issues
from labcatalog.pipeline import run_check, run_validate

WINDOW_SIZE = (1100, 750)

ISSUE_COLUMNS = [
    {"name": "level", "label": "Level", "field": "level", "align": "left", "sortable": True},
    {"name": "location", "label": "File", "field": "location", "align": "left", "sortable": True},
    {"name": "message", "label": "Problem", "field": "message", "align": "left"},
    {"name": "code", "label": "Code", "field": "code", "align": "left"},
]


def launch() -> None:
    ui.run(
        root=main_page,
        title=f"labcatalog {__version__}",
        native=True,
        window_size=WINDOW_SIZE,
        reload=False,
        show_welcome_message=False,
    )


def main_page() -> None:
    project_root: Path | None = None

    # A packaged app has no console, so unexpected errors must show up in the window.
    ui.on_exception(
        lambda err: ui.notify(
            f"Unexpected error: {err!r}", type="negative", multi_line=True, timeout=0
        )
    )

    async def open_folder() -> None:
        nonlocal project_root
        selection = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
        if not selection:
            return
        project_root = Path(selection[0])
        folder_label.set_text(str(project_root))
        for button in check_buttons:
            button.enable()
        await check_metadata()

    async def check_metadata() -> None:
        await show_issues(lambda: run_validate(project_root))

    async def check_data() -> None:
        await show_issues(lambda: run_check(project_root).issues)

    async def show_issues(task) -> None:
        try:
            issues = await run.io_bound(task)
        except LabCatalogError as err:
            summary.set_text("")
            table.update_rows([])
            ui.notify(str(err), type="negative", multi_line=True)
            return
        summary.set_text(summarize_issues(issues))
        table.update_rows([{"id": i, **issue.model_dump()} for i, issue in enumerate(issues)])

    with ui.column().classes("w-full p-4 gap-4"):
        ui.label("labcatalog").classes("text-2xl font-bold")
        with ui.row().classes("items-center gap-4"):
            ui.button("Open project folder", icon="folder_open", on_click=open_folder)
            folder_label = ui.label("No project open").classes("text-grey-7")
        with ui.row().classes("gap-2"):
            check_buttons = [
                ui.button("Check metadata", icon="fact_check", on_click=check_metadata),
                ui.button("Check data", icon="table_view", on_click=check_data),
            ]
        for button in check_buttons:
            button.disable()
        summary = ui.label().classes("text-lg")
        table = ui.table(columns=ISSUE_COLUMNS, rows=[], row_key="id").classes("w-full")
