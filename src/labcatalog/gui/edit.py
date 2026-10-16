import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from nicegui import ui

from labcatalog import editing
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import heading, note
from labcatalog.issues import Issue

LINE = re.compile(r":(\d+)$")


@dataclass
class EditView:
    path: str | None = None


@dataclass
class Shown:
    # What the page shows now, replaced each time another file opens.
    opened: editing.Opened
    editor: ui.codemirror | None = None
    problems: ui.column | None = None


def render(root: Path, view: EditView, on_saved: Callable[[], Awaitable[None]]) -> None:
    files = editing.editable_files(root)
    paths = [p for group in files.values() for p in group]
    if view.path not in paths:
        view.path = paths[0]
    shown = Shown(editing.open_file(root, view.path))

    def changed() -> bool:
        return shown.editor.value != shown.opened.text

    def choose(path: str) -> None:
        if path == view.path:
            return
        if not changed():
            go(path)
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Discard your changes to {view.path}?")
            with ui.row():
                ui.button("Discard", on_click=lambda: (dialog.close(), go(path)))
                ui.button("Keep editing", on_click=dialog.close).props("flat")
        dialog.open()

    def go(path: str) -> None:
        view.path = path
        page.refresh()

    async def save() -> None:
        issues = editing.check_text(view.path, shown.editor.value)
        show(issues)
        if issues:
            ui.notify("Not saved: fix the problems listed under the editor", type="warning")
            return
        try:
            shown.opened = editing.save_file(root, shown.opened, shown.editor.value)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        ui.notify(f"Saved {view.path}")
        await on_saved()

    def reload() -> None:
        shown.opened = editing.open_file(root, view.path)
        shown.editor.value = shown.opened.text
        show([])

    def show(issues: list[Issue]) -> None:
        shown.editor.line_tooltips = {
            int(found.group(1)): issue.message
            for issue in issues
            if issue.location and (found := LINE.search(issue.location))
        }
        shown.problems.clear()
        with shown.problems:
            for issue in issues:
                where = LINE.search(issue.location or "")
                line = f"Line {where.group(1)}: " if where else ""
                ui.label(f"{line}{issue.message}").classes("text-negative")

    def create() -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label("New instrument")
            name = ui.input("ID", placeholder="for example parent_stress").classes("w-72")

            def make() -> None:
                try:
                    path = editing.new_instrument(root, (name.value or "").strip())
                except LabCatalogError as err:
                    ui.notify(str(err), type="negative")
                    return
                dialog.close()
                go(path)

            with ui.row():
                ui.button("Create", on_click=make)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    @ui.refreshable
    def page() -> None:
        shown.opened = opened = editing.open_file(root, view.path)
        with ui.row().classes("w-full no-wrap items-start gap-6"):
            with ui.column().classes("gap-0 w-60 shrink-0"):
                for group, members in editing.editable_files(root).items():
                    if not members:
                        continue
                    heading(group)
                    for path in members:
                        item = ui.item(Path(path).name, on_click=partial(choose, path)).props(
                            "dense clickable"
                        )
                        if path == view.path:
                            item.classes("bg-blue-1 font-medium")
                ui.button("New instrument", icon="add", on_click=create).props(
                    "flat dense no-caps"
                ).classes("mt-2")
            with ui.column().classes("grow min-w-0 gap-2"):
                ui.label(opened.path).classes("font-medium")
                note(
                    "Saving checks the file the way loading the project does and keeps it as it "
                    "was if something is wrong; then the catalog reloads."
                )
                shown.editor = (
                    ui.codemirror(
                        opened.text,
                        language=None if opened.path.endswith(".csv") else "YAML",
                        indent="  ",
                        line_wrapping=True,
                    )
                    .classes("w-full")
                    .style("height: 65vh")
                )
                with ui.row().classes("items-center gap-3"):
                    ui.button("Save", icon="save", on_click=save)
                    ui.button("Reload from disk", icon="refresh", on_click=reload).props(
                        "flat no-caps"
                    )
                shown.problems = ui.column().classes("gap-1")

    page()
