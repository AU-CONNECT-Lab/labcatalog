import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from nicegui import ui

from labcatalog import editing, records
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import heading, note
from labcatalog.issues import Issue

LINE = re.compile(r":(\d+)$")
TEXT = "text"
WIDE = {"text", "label", "path"}


@dataclass
class EditView:
    path: str | None = None
    mode: str = TEXT


@dataclass
class Shown:
    # What the page shows now, replaced each time another file or table opens.
    opened: editing.Opened
    editor: ui.codemirror | None = None
    grid: ui.aggrid | None = None
    problems: ui.column | None = None
    edited: bool = False


def render(root: Path, view: EditView, on_saved: Callable[[], Awaitable[None]]) -> None:
    files = editing.editable_files(root)
    paths = [p for group in files.values() for p in group]
    if view.path not in paths:
        view.path = paths[0]
    shown = Shown(editing.open_file(root, view.path))

    def changed() -> bool:
        if shown.editor is not None:
            return shown.editor.value != shown.opened.text
        return shown.edited

    def leave(then: Callable[[], None]) -> None:
        if not changed():
            then()
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Discard your changes to {view.path}?")
            with ui.row():
                ui.button("Discard", on_click=lambda: (dialog.close(), then()))
                ui.button("Keep editing", on_click=dialog.close).props("flat")
        dialog.open()

    def choose(path: str) -> None:
        if path != view.path:
            leave(partial(go, path, TEXT))

    def switch(mode: str) -> None:
        if mode != view.mode:
            leave(partial(go, view.path, mode))

    def go(path: str, mode: str) -> None:
        view.path, view.mode = path, mode
        page.refresh()

    async def write(text: str) -> None:
        issues = editing.check_text(view.path, text)
        show(issues)
        if issues:
            ui.notify("Not saved: fix the problems listed below", type="warning")
            return
        try:
            shown.opened = editing.save_file(root, shown.opened, text)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        shown.edited = False
        ui.notify(f"Saved {view.path}")
        await on_saved()

    async def save_text() -> None:
        await write(shown.editor.value)

    async def save_table() -> None:
        rows = await shown.grid.get_client_data()
        try:
            text = records.write_rows(shown.opened.text, view.mode, table(), rows)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative")
            return
        await write(text)

    async def add_row() -> None:
        rows = await shown.grid.get_client_data()
        new = {c.key: cell(records.shown(None, c), c) for c in table().columns}
        if table().inner and rows:
            # A new option most often joins the set above it.
            first = table().columns[0].key
            new[first] = rows[-1][first]
        set_rows([*rows, new])

    async def delete_rows() -> None:
        selected = await shown.grid.get_selected_rows()
        if not selected:
            ui.notify("Tick the rows to delete first")
            return
        set_rows([r for r in await shown.grid.get_client_data() if r not in selected])

    def set_rows(rows: list[dict]) -> None:
        shown.grid.options["rowData"] = rows
        shown.grid.update()
        shown.edited = True

    def reload() -> None:
        shown.edited = False
        page.refresh()

    def table() -> records.Table:
        return records.tables_for(view.path)[view.mode]

    def show(issues: list[Issue]) -> None:
        if shown.editor is not None:
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
                go(path, TEXT)

            with ui.row():
                ui.button("Create", on_click=make)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    def text_mode(opened: editing.Opened) -> None:
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
            ui.button("Save", icon="save", on_click=save_text)
            ui.button("Reload from disk", icon="refresh", on_click=reload).props("flat no-caps")

    def table_mode(opened: editing.Opened) -> None:
        rows = records.read_rows(opened.text, view.mode, table())
        shown.grid = (
            ui.aggrid(grid_options(table().columns, rows))
            .classes("w-full")
            .style("height: 65vh")
            .on("cellValueChanged", lambda: setattr(shown, "edited", True))
        )
        with ui.row().classes("items-center gap-3"):
            ui.button("Save", icon="save", on_click=save_table)
            ui.button("Add row", icon="add", on_click=add_row).props("flat no-caps")
            ui.button("Delete ticked rows", icon="delete", on_click=delete_rows).props(
                "flat no-caps"
            )
            ui.button("Reload from disk", icon="refresh", on_click=reload).props("flat no-caps")
        note(
            "Lists are written with commas, for example ems_1, ems_2. Saving changes only the "
            "cells you changed, so comments and the rest of the file stay as they were."
        )
        if table().inner:
            note(
                f"Rows with the same {table().columns[0].label} make one entry. Renaming it here "
                "does not rename it where other parts of the file use it."
            )

    @ui.refreshable
    def page() -> None:
        shown.opened = opened = editing.open_file(root, view.path)
        shown.editor = shown.grid = None
        tables = records.tables_for(view.path)
        if view.mode not in tables:
            view.mode = TEXT
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
                with ui.row().classes("items-center gap-4"):
                    ui.label(opened.path).classes("font-medium")
                    if tables:
                        ui.toggle(
                            {TEXT: "Text", **{key: t.label for key, t in tables.items()}},
                            value=view.mode,
                            on_change=lambda e: switch(e.value),
                        ).props("dense no-caps")
                note(
                    "Saving checks the file the way loading the project does and keeps it as it "
                    "was if something is wrong; then the catalog reloads."
                )
                if view.mode == TEXT:
                    text_mode(opened)
                else:
                    try:
                        table_mode(opened)
                    except LabCatalogError as err:
                        note(str(err))
                shown.problems = ui.column().classes("gap-1")

    page()


def grid_options(columns: tuple[records.Column, ...], rows: list[dict]) -> dict:
    definitions = []
    for column in columns:
        definition = {
            "field": column.key,
            "headerName": column.label,
            "editable": True,
            "flex": 3 if column.key in WIDE else 1,
            "minWidth": 280 if column.key in WIDE else 90,
            "cellDataType": {"bool": "boolean", "number": "number"}.get(column.kind, "text"),
        }
        if column.kind == "choice":
            definition["cellEditor"] = "agSelectCellEditor"
            definition["cellEditorParams"] = {"values": list(column.choices)}
        definitions.append(definition)
    return {
        "columnDefs": definitions,
        "rowData": [
            {c.key: cell(row[c.key], c) for c in columns} | row_origin(row) for row in rows
        ],
        "rowSelection": {"mode": "multiRow"},
        "stopEditingWhenCellsLoseFocus": True,
        "defaultColDef": {"resizable": True},
    }


def cell(value, column: records.Column):
    # The grid's number cells take an empty value as null, not as an empty string.
    return None if column.kind == "number" and value == "" else value


def row_origin(row: dict) -> dict:
    return {records.ORIGIN: row[records.ORIGIN]}
