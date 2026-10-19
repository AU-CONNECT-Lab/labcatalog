from pathlib import Path

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common
from labcatalog.gui.common import note
from labcatalog.gui.files import FOLDER, allowed, choose_path
from labcatalog.project import init_project


async def new_project_dialog(start: Path | None) -> Path | None:
    # Returns the new project's folder, with empty settings and the schemas editors read.
    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label("New project").classes("text-lg font-medium")
        note(
            "labcatalog makes a folder of this name with an empty labcatalog.yaml and the folders "
            "a project uses, then opens it."
        )
        name = ui.input("Name", placeholder="sleep_study").classes("w-full")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            folder = ui.input("In the folder", value=str(start or common.serving or "")).classes(
                "grow"
            )

            async def pick() -> None:
                found = await choose_path(
                    FOLDER, start=Path(folder.value) if folder.value else None
                )
                if found:
                    folder.value = str(found)

            ui.button("Choose", on_click=pick).props("flat no-caps")

        def make() -> None:
            given = (name.value or "").strip()
            if not given or not folder.value:
                ui.notify("Give the project a name and a folder to put it in", type="warning")
                return
            target = Path(folder.value) / given
            if not allowed(target):
                ui.notify(f"Choose a folder inside {common.serving}", type="warning")
                return
            try:
                dialog.submit(init_project(target, example=False))
            except LabCatalogError as err:
                ui.notify(str(err), type="negative", multi_line=True)

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
            ui.button("Create", on_click=make)
    try:
        return await dialog
    finally:
        dialog.delete()
