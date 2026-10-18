import fnmatch
from pathlib import Path

from nicegui import app, ui

from labcatalog.gui import common

FILE = "file"
FOLDER = "folder"
PDF_FILES = "PDF files (*.pdf)"


async def choose_path(
    kind: str = FILE, file_types: tuple[str, ...] = (), start: Path | None = None
) -> Path | None:
    if common.native:
        import webview

        dialog = webview.FileDialog.FOLDER if kind == FOLDER else webview.FileDialog.OPEN
        selection = await app.native.main_window.create_file_dialog(
            dialog, directory=str(start or ""), file_types=file_types
        )
        return Path(selection[0]) if selection else None
    return await browse(kind, patterns(file_types), start or common.serving or Path.home())


def patterns(file_types: tuple[str, ...]) -> list[str]:
    # "CSV files (*.csv;*.tsv)" gives *.csv and *.tsv, as the system dialogs read it.
    found = []
    for kind in file_types:
        inside = kind[kind.rfind("(") + 1 : kind.rfind(")")]
        found += [p.strip().lower() for p in inside.split(";") if p.strip()]
    return found


def allowed(path: Path) -> bool:
    # Serving several people, the chooser stays inside the folder of projects.
    return common.serving is None or path.resolve().is_relative_to(common.serving)


def listing(folder: Path, shown: list[str], kind: str) -> tuple[list[Path], list[Path]]:
    entries = sorted(
        (p for p in folder.iterdir() if not p.name.startswith(".")), key=lambda p: p.name.lower()
    )
    folders = [p for p in entries if p.is_dir()]
    if kind == FOLDER:
        return folders, []
    files = [
        p
        for p in entries
        if p.is_file() and (not shown or any(fnmatch.fnmatch(p.name.lower(), s) for s in shown))
    ]
    return folders, files


async def browse(kind: str, shown: list[str], start: Path) -> Path | None:
    # A browser's own file dialog sees the viewer's computer; the files are where labcatalog runs.
    state: dict[str, Path | None] = {"folder": start if start.is_dir() else start.parent}
    state["picked"] = None if start.is_dir() else start
    with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full"):
        ui.label("Choose a folder" if kind == FOLDER else "Choose a file").classes("lc-subhead")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            ui.button(icon="arrow_upward", on_click=lambda: go(state["folder"].parent)).props(
                "flat round dense"
            ).tooltip("Up one folder")
            where = ui.input("Folder").props("outlined dense").classes("grow")
            where.on("keydown.enter", lambda: typed(where.value))
        problem = ui.label().classes("lc-note text-negative")
        with ui.scroll_area().classes("h-80 w-full"):
            entries = ui.column().classes("w-full gap-0")
        with ui.row().classes("w-full items-center justify-end"):
            picked = ui.label().classes("lc-note grow min-w-0")
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
            chosen = ui.button("Choose", on_click=lambda: dialog.submit(answer()))

    def answer() -> Path | None:
        return state["folder"] if kind == FOLDER else state["picked"]

    def typed(text: str) -> None:
        path = Path((text or "").strip()).expanduser()
        if path.is_file() and kind == FILE and allowed(path):
            state["picked"] = path
            go(path.parent)
        else:
            go(path)

    def go(folder: Path) -> None:
        if not allowed(folder):
            problem.set_text(f"Only folders inside {common.serving} can be chosen here.")
            where.set_value(str(state["folder"]))
            return
        try:
            folders, files = listing(folder, shown, kind)
        except OSError as err:
            problem.set_text(f"Cannot open {folder}: {err.strerror or err}")
            where.set_value(str(state["folder"]))
            return
        problem.set_text("")
        state["folder"] = folder
        if state["picked"] is not None and state["picked"].parent != folder:
            state["picked"] = None
        where.set_value(str(folder))
        entries.clear()
        rows.clear()
        with entries:
            for path in folders:
                row(path, "folder", lambda p=path: go(p))
            for path in files:
                rows[path] = row(path, "description", lambda p=path: pick(p))
                rows[path].on("dblclick", lambda p=path: dialog.submit(p))
        pick(state["picked"])

    def pick(path: Path | None) -> None:
        # Only the highlight moves, so a double click still finds the row it started on.
        for each, shown_row in rows.items():
            shown_row.classes(**{"add" if each == path else "remove": "lc-info"})
        state["picked"] = path
        show_answer()

    rows: dict[Path, ui.row] = {}

    def show_answer() -> None:
        found = answer()
        picked.set_text(str(found) if found else "")
        chosen.set_enabled(found is not None)

    go(state["folder"])
    try:
        return await dialog
    finally:
        dialog.delete()


def row(path: Path, icon: str, on_click) -> ui.row:
    with ui.row().classes("lc-pick w-full items-center no-wrap gap-2 cursor-pointer") as found:
        ui.icon(icon).classes("lc-faint")
        ui.label(path.name).classes("min-w-0")
    found.on("click", on_click)
    return found
