from pathlib import Path

from nicegui import ui

from labcatalog import defaults
from labcatalog.gui import common, preferences
from labcatalog.gui.common import computed, empty, note, panel
from labcatalog.gui.look import Look
from labcatalog.project import find_projects
from labcatalog.stats import rbridge


def start_folder() -> Path | None:
    # The project this browser had open last, while it is still among the projects served.
    last = preferences.mine().get(preferences.LAST_PROJECT)
    if not last:
        return None
    path = Path(last)
    inside = path.resolve().is_relative_to(common.serving)
    return path if inside and (path / defaults.CONFIG_FILENAME).is_file() else None


async def ask_name(look: Look) -> None:
    with ui.dialog().props("persistent") as dialog, ui.card().classes("w-96"):
        ui.label("Your name").classes("lc-subhead")
        note(
            "Everyone here shares this labcatalog, so what you change carries your name: "
            "accepted warnings, prepare steps you run and data versions you save."
        )
        name = ui.input("Name", value=look.who or "").props("autofocus").classes("w-full")

        def done() -> None:
            if (name.value or "").strip():
                dialog.submit(name.value.strip())

        name.on("keydown.enter", done)
        with ui.row().classes("w-full justify-end"):
            ui.button("Save", on_click=done)
    try:
        given = await dialog
    finally:
        dialog.delete()
    look.who = given
    preferences.save_mine({preferences.WHO: given})


async def choose_project(current: Path | None) -> Path | None:
    found = await computed(find_projects, common.serving)
    with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
        ui.label("Open a project").classes("lc-subhead")
        note(f"The projects in {common.serving}.")
        if not found:
            empty(f"No folder here has a {defaults.CONFIG_FILENAME}.", "folder_off")
        with ui.scroll_area().classes("h-80 w-full"):
            for path in found:
                shown = (
                    path.relative_to(common.serving).as_posix()
                    if path != common.serving
                    else path.name
                )
                with ui.row().classes(
                    "lc-pick w-full items-center no-wrap gap-2 cursor-pointer"
                ) as row:
                    ui.icon("folder").classes("lc-faint")
                    ui.label(shown).classes("min-w-0")
                    if path == current:
                        ui.label("open").classes("lc-pill")
                row.on("click", lambda p=path: dialog.submit(p))
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
    try:
        return await dialog
    finally:
        dialog.delete()


def server_section() -> None:
    saved = preferences.load()
    with panel(
        "Set where labcatalog runs",
        "This labcatalog serves several people, so the programs it runs are set by whoever "
        f"runs it, in {preferences.folder() / preferences.FILENAME}.",
    ):
        rows = [
            ("Rscript", saved.get(preferences.RSCRIPT) or "not set"),
            ("Mplus", saved.get(preferences.MPLUS) or "not set"),
            ("DataLad", saved.get(preferences.DATALAD) or "not set"),
            (
                "Analyses in R at once",
                str(saved.get(preferences.R_AT_ONCE, rbridge.DEFAULT_AT_ONCE)),
            ),
            ("Language model server", saved.get(preferences.LLM_URL) or "not set"),
        ]
        common.table(
            [common.col("setting", "Setting"), common.col("value", "Value")],
            [{"setting": k, "value": v} for k, v in rows],
        )
