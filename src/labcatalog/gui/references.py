from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import ui

from labcatalog import defaults
from labcatalog.config import ProjectConfig
from labcatalog.gui.common import note
from labcatalog.metadata import bibliography
from labcatalog.paths import portable_path
from labcatalog.project import bib_path


def add_dialog(
    config: ProjectConfig, root: Path, on_added: Callable[[list[str]], Awaitable[None]]
) -> None:
    path = bib_path(config, root)
    existing = bibliography.load_bibliography(path, root, [])
    found: list[bibliography.Pasted] = []
    problems: list[str] = []

    def read(text: str) -> None:
        entries, issues = bibliography.pasted_entries(text, existing)
        found[:] = entries
        problems[:] = [f"{i.location}: {i.message}" for i in issues]
        preview.refresh()

    async def add() -> None:
        added = bibliography.add_entries(path, found)
        dialog.close()
        ui.notify(
            f"Added {', '.join(added)} to {defaults.BIB_FILENAME}" if added else "Nothing new"
        )
        await on_added(added)

    @ui.refreshable
    def preview() -> None:
        for entry in found:
            with ui.row().classes("w-full items-baseline gap-3 no-wrap"):
                ui.label(entry.key).classes("font-medium shrink-0")
                ui.label(entry.title).classes("grow")
                if entry.taken:
                    ui.label(f"already in {defaults.BIB_FILENAME}").classes("lc-note shrink-0")
        for line in problems:
            ui.label(line).classes("lc-bad-text")
        new = sum(not e.taken for e in found)
        with ui.row().classes("gap-2"):
            ui.button(f"Add {new}" if new else "Add", on_click=add).props(
                "no-caps" if new else "no-caps disable"
            )
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")

    with ui.dialog() as dialog, ui.card().classes("w-[48rem] max-w-full"):
        ui.label("Add references").classes("text-lg font-medium")
        where = portable_path(path, root).as_posix()
        note(
            f"Paste BibTeX entries; they go at the end of {where}. In Zotero, set Quick Copy to "
            "BibTeX, select the items and press Ctrl+Shift+C."
        )
        ui.textarea("BibTeX", on_change=lambda e: read(e.value or "")).props("outlined").classes(
            "lc-grow w-full font-mono"
        )
        preview()
    dialog.open()
