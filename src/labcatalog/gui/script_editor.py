from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import theme
from labcatalog.gui.common import open_path
from labcatalog.metadata import editing
from labcatalog.metadata.scripts import LANGUAGES, language_of


def script_editor(
    root: Path,
    path: str,
    tools: ui.element,
    height: str = "55vh",
    on_edit: Callable[[], None] | None = None,
    on_saved: Callable[[], None] | None = None,
) -> None:
    # The code of one script, with Save and Open in your editor put in tools.
    opened = editing.open_file(root, path)
    language = language_of(path)

    def touched() -> None:
        save.enable()
        if on_edit:
            on_edit()

    def saved() -> None:
        nonlocal opened
        try:
            opened = editing.save_file(root, opened, code.value)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        save.disable()
        ui.notify(f"Saved {path}")
        if on_saved:
            on_saved()

    code = (
        ui.codemirror(
            opened.text,
            language=LANGUAGES[language].name if language else None,
            line_wrapping=True,
            theme=theme.codemirror_theme(),
            on_change=touched,
        )
        .classes("w-full")
        .style(f"height: {height}")
    )
    with tools:
        ui.button(
            "Open in your editor", icon="open_in_new", on_click=lambda: open_path(root / path)
        ).props("flat dense no-caps").classes("lc-quiet-btn")
        save = ui.button("Save", icon="save", on_click=saved).props("dense no-caps")
        save.disable()
