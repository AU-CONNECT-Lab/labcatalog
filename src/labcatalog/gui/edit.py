from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import webview
from nicegui import app, ui

from labcatalog import defaults
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences, theme
from labcatalog.gui.common import LINE_SUFFIX, computed, note, panel
from labcatalog.issues import Issue
from labcatalog.metadata import editing, records
from labcatalog.pipeline import run_instrument_draft

TEXT = "text"
WIDE = {"text", "label", "path", "instrument", "datasets", "administration"}


@dataclass
class EditView:
    path: str | None = None
    mode: str = TEXT
    # The line to show once the file opens, as when coming from the Problems page.
    line: int | None = None
    # Set by the page, so other pages can open a file in it.
    open: Callable[[str, int | None], None] | None = None


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
    fields = editing.custom_fields(root)
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
        # Inside this page even when another page asks, so the question shows here.
        with frame, ui.dialog() as dialog, ui.card():
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

    def go(path: str, mode: str, line: int | None = None) -> None:
        view.path, view.mode, view.line = path, mode, line
        page.refresh()

    def jump(path: str, line: int | None) -> None:
        if path == view.path and shown.editor is not None:
            mark(line)
        else:
            leave(partial(go, path, TEXT, line))

    def mark(line: int | None) -> None:
        if line is None:
            return
        shown.editor.decorations = [{"kind": "line", "line": line, "class": "lc-mark"}]
        # The editor mounts after the Edit tab shows.
        ui.timer(0.3, partial(shown.editor.reveal_line, line), once=True)

    def write(text: str) -> bool:
        issues = editing.check_text(view.path, text)
        show(issues)
        if issues:
            ui.notify("Not saved: fix the problems listed below", type="warning")
            return False
        try:
            shown.opened = editing.save_file(root, shown.opened, text)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return False
        shown.edited = False
        return True

    async def edited_text() -> str | None:
        if shown.editor is not None:
            return shown.editor.value
        rows = await shown.grid.get_client_data(method="filtered_sorted")
        try:
            return records.write_rows(shown.opened.text, view.mode, table(), rows)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative")
            return None

    async def save() -> None:
        text = await edited_text()
        if text is not None and write(text):
            ui.notify(f"Saved {view.path}")
            await on_saved()

    async def move() -> None:
        text = await edited_text()
        if text is None or not write(text):
            return
        try:
            path = editing.move_draft(root, view.path)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative")
            return
        ui.notify(f"Moved to {path}")
        go(path, TEXT)
        await on_saved()

    async def add_row() -> None:
        rows = await shown.grid.get_client_data(method="filtered_sorted")
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
        set_rows(
            [
                r
                for r in await shown.grid.get_client_data(method="filtered_sorted")
                if r not in selected
            ]
        )

    def set_rows(rows: list[dict]) -> None:
        shown.grid.options["rowData"] = rows
        shown.grid.update()
        shown.edited = True

    def reload() -> None:
        shown.edited = False
        page.refresh()

    def table() -> records.Table:
        return records.with_entries(
            records.tables_for(view.path, fields)[view.mode], shown.opened.text
        )

    def show(issues: list[Issue]) -> None:
        if shown.editor is not None:
            shown.editor.line_tooltips = {
                int(found.group(1)): issue.message
                for issue in issues
                if issue.location and (found := LINE_SUFFIX.search(issue.location))
            }
        shown.problems.clear()
        with shown.problems:
            for issue in issues:
                where = LINE_SUFFIX.search(issue.location or "")
                line = f"Line {where.group(1)}: " if where else ""
                ui.label(f"{line}{issue.message}").classes("text-negative")

    def create() -> None:
        with frame, ui.dialog() as dialog, ui.card():
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

    def draft() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
            ui.label("New instrument from a PDF")
            if not preferences.model_set():
                note("Set a language model on the Settings page to draft an instrument from a PDF.")
                ui.button("Close", on_click=dialog.close).props("flat")
                dialog.open()
                return
            name = ui.input("ID", placeholder="for example parent_stress").classes("w-72")
            chosen: list[Path] = []

            async def pick() -> None:
                selection = await app.native.main_window.create_file_dialog(
                    webview.FileDialog.OPEN, file_types=("PDF files (*.pdf)",)
                )
                if selection:
                    chosen[:] = [Path(selection[0])]
                    picked.set_text(chosen[0].name)

            async def make() -> None:
                if not chosen:
                    ui.notify("Choose the PDF first")
                    return
                button.disable()
                status.set_text("Reading the PDF and drafting the instrument.")
                settings = preferences.load()
                try:
                    drafted = await computed(
                        run_instrument_draft,
                        root,
                        (name.value or "").strip(),
                        chosen[0],
                        settings.get(preferences.LLM_PROVIDER, preferences.DEFAULT_LLM_PROVIDER),
                        settings.get(preferences.LLM_MODEL, ""),
                        settings.get(preferences.LLM_URL, ""),
                    )
                except LabCatalogError as err:
                    status.set_text(str(err))
                    button.enable()
                    return
                dialog.close()
                meta = drafted.meta
                ui.notify(
                    f"Drafted by {meta.model} in {meta.latency_ms / 1000:.0f} s, "
                    f"{meta.input_tokens} tokens in and {meta.output_tokens} out"
                )
                leave(partial(go, drafted.path.relative_to(root).as_posix(), TEXT))

            with ui.row().classes("items-center gap-3"):
                ui.button("Choose the PDF", icon="picture_as_pdf", on_click=pick).props(
                    "flat no-caps"
                )
                picked = ui.label()
            note(
                f"The draft goes into {defaults.DRAFTS_DIR}/, replacing a draft with the "
                "same ID, and stays out of the catalog until you move it to instruments/. The "
                "PDF's text, including the item wording, is sent to the model's provider."
            )
            with ui.row():
                button = ui.button("Draft", on_click=make)
                ui.button("Cancel", on_click=dialog.close).props("flat")
            status = ui.label().classes("lc-note")
        dialog.open()

    def save_buttons() -> None:
        ui.button("Save", icon="save", on_click=save)
        if editing.is_draft(view.path):
            ui.button("Move to instruments", icon="drive_file_move", on_click=move).props(
                "flat no-caps"
            )

    def text_mode(opened: editing.Opened) -> None:
        shown.editor = (
            ui.codemirror(
                opened.text,
                language=None if opened.path.endswith(".csv") else "YAML",
                indent="  ",
                line_wrapping=True,
                theme=theme.codemirror_theme(),
            )
            .classes("w-full")
            .style("height: 65vh")
        )
        mark(view.line)
        view.line = None
        with ui.row().classes("lc-actions items-center gap-3"):
            save_buttons()
            ui.button("Reload from disk", icon="refresh", on_click=reload).props("flat no-caps")

    def table_mode(opened: editing.Opened) -> None:
        rows = records.read_rows(opened.text, view.mode, table())
        shown.grid = (
            ui.aggrid(grid_options(table(), rows))
            .classes("w-full")
            .style("height: 7rem" if table().single else "height: 65vh")
            .on("cellValueChanged", lambda: setattr(shown, "edited", True))
            .on("rowDragEnd", lambda: setattr(shown, "edited", True))
        )
        with ui.row().classes("lc-actions items-center gap-3"):
            save_buttons()
            if not table().single:
                ui.button("Add row", icon="add", on_click=add_row).props("flat no-caps")
                ui.button("Delete ticked rows", icon="delete", on_click=delete_rows).props(
                    "flat no-caps"
                )
            ui.button("Reload from disk", icon="refresh", on_click=reload).props("flat no-caps")
        note(
            "Lists are written with commas, for example ems_1, ems_2."
            + ("" if table().single else " Drag a row by its handle to move it.")
            + " Saving changes only the cells you changed, so comments and the rest of the file "
            "stay as they were."
        )
        if table().parent:
            note(
                "Each row changes one item in the administration chosen first; leave Dataset "
                "empty for every dataset of that administration."
            )
        elif table().inner:
            note(
                f"Rows with the same {table().columns[0].label} make one entry. Renaming it here "
                "does not rename it where other parts of the file use it."
            )
        for column in table().columns:
            if column.kind == "list" and column.choices:
                note(f"{column.label} takes one or more of: {', '.join(column.choices)}.")

    @ui.refreshable
    def page() -> None:
        shown.opened = opened = editing.open_file(root, view.path)
        shown.editor = shown.grid = None
        tables = records.tables_for(view.path, fields)
        if view.mode not in tables:
            view.mode = TEXT
        with ui.row().classes("w-full no-wrap items-start gap-4"):
            with ui.column().classes("w-64 shrink-0 lc-sticky"), panel("Files"):
                for group, members in editing.editable_files(root).items():
                    if not members:
                        continue
                    ui.label(group).classes("lc-facet")
                    for path in members:
                        item = (
                            ui.item(Path(path).name, on_click=partial(choose, path))
                            .props("dense clickable")
                            .classes("lc-pick")
                        )
                        if path == view.path:
                            item.classes("lc-info font-medium")
                ui.button("New instrument", icon="add", on_click=lambda: leave(create)).props(
                    "flat dense no-caps"
                ).classes("mt-2")
                ui.button("New instrument from a PDF", icon="picture_as_pdf", on_click=draft).props(
                    "flat dense no-caps"
                )
            with (
                ui.column().classes("grow min-w-0"),
                panel(
                    opened.path,
                    "Saving checks the file the way loading the project does and keeps it as it "
                    "was if something is wrong; then the catalog reloads.",
                ) as tools,
            ):
                if tables:
                    with tools:
                        ui.toggle(
                            {TEXT: "Text", **{key: t.label for key, t in tables.items()}},
                            value=view.mode,
                            on_change=lambda e: switch(e.value),
                        ).props("dense no-caps")
                if editing.is_draft(view.path):
                    ui.label(
                        "A draft from a PDF, kept out of the catalog. Check it against the PDF "
                        "and add its reference, then move it to instruments/."
                    ).classes("lc-status lc-warn")
                if view.mode == TEXT:
                    text_mode(opened)
                else:
                    try:
                        table_mode(opened)
                    except LabCatalogError as err:
                        note(str(err))
                shown.problems = ui.column().classes("gap-1")

    view.open = jump
    with ui.element("div").classes("w-full") as frame:
        page()


def grid_options(table: records.Table, rows: list[dict]) -> dict:
    columns = table.columns
    definitions = []
    for column in columns:
        # Tags and notes in custom fields run long, like the built-in text columns.
        wide = column.key in WIDE or (
            column.key.startswith(records.CUSTOM + records.NESTED) and column.kind != "choice"
        )
        definition = {
            "field": column.key,
            "headerName": column.label,
            "editable": True,
            "flex": 3 if wide else 1,
            "minWidth": 280 if wide else 90,
            "cellDataType": {"bool": "boolean", "number": "number"}.get(column.kind, "text"),
        }
        if column is columns[0] and not table.single:
            # A handle to drag the row up or down.
            definition["rowDrag"] = True
        if column.kind == "choice":
            definition["cellEditor"] = "agSelectCellEditor"
            definition["cellEditorParams"] = {"values": list(column.choices)}
        definitions.append(definition)
    return {
        "columnDefs": definitions,
        "rowData": [
            {c.key: cell(row[c.key], c) for c in columns} | row_origin(row) for row in rows
        ],
        "stopEditingWhenCellsLoseFocus": True,
        "defaultColDef": {"resizable": True},
    } | ({} if table.single else {"rowSelection": {"mode": "multiRow"}, "rowDragManaged": True})


def cell(value, column: records.Column):
    # The grid's number cells take an empty value as null, not as an empty string.
    return None if column.kind == "number" and value == "" else value


def row_origin(row: dict) -> dict:
    return {records.ORIGIN: row[records.ORIGIN]}
