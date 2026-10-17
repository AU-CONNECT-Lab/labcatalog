import asyncio
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from nicegui import run, ui

from labcatalog import defaults
from labcatalog.metadata.bibliography import Bibliography, citation
from labcatalog.stats.summary import wave_order

LINE_SUFFIX = re.compile(r":(\d+)$")
ROW_KEY = "_row"


def col(name: str, label: str, *, numeric: bool = False, sortable: bool = True) -> dict:
    align = "right" if numeric else "left"
    return {"name": name, "label": label, "field": name, "align": align, "sortable": sortable}


def table(columns: list[dict], rows: list[dict], pagination: int | None = None) -> ui.table:
    return (
        ui.table(columns=columns, rows=keyed(rows), row_key=ROW_KEY, pagination=pagination)
        .props("flat bordered dense wrap-cells")
        .classes("w-full")
    )


def keyed(rows: list[dict]) -> list[dict]:
    return [{ROW_KEY: i, **row} for i, row in enumerate(rows)]


async def computed(callback, *args):
    # NiceGUI gives None in place of the result while the window closes.
    found = await run.io_bound(callback, *args)
    if found is None:
        raise asyncio.CancelledError
    return found


@contextmanager
def panel(title: str, subtitle: str = "") -> Iterator[ui.row]:
    # Yields the title bar's right-hand row, for controls that belong to the panel.
    with ui.column().classes("lc-panel w-full gap-0"):
        with ui.row().classes("lc-panel-head w-full items-center no-wrap gap-4"):
            with ui.column().classes("grow gap-0"):
                ui.label(title).classes("lc-panel-title")
                if subtitle:
                    ui.label(subtitle).classes("lc-panel-subtitle")
            tools = ui.row().classes("items-center no-wrap gap-3")
        with ui.column().classes("lc-panel-body w-full gap-2"):
            yield tools


def page_head(title: str, summary: str = "", help_text: str = "") -> ui.row:
    # Returns the right-hand row, for the page's own actions.
    with ui.row().classes("lc-page-head w-full items-center no-wrap gap-4"):
        with ui.column().classes("grow gap-0 min-w-0"):
            with ui.row().classes("items-center no-wrap gap-1"):
                ui.label(title).classes("lc-page-title")
                if help_text:
                    help_button(help_text)
            if summary:
                ui.label(summary).classes("lc-page-summary")
        return ui.row().classes("items-center gap-2")


def help_button(text: str) -> None:
    with ui.button(icon="help_outline").props("flat round dense size=sm").classes("lc-help-btn"):
        with ui.menu().props("anchor='bottom left' self='top left'"):
            ui.label(text).classes("lc-help")


def empty(text: str, icon: str = "inbox") -> None:
    with ui.column().classes("lc-empty w-full items-center gap-2"):
        ui.icon(icon).classes("lc-empty-icon")
        ui.label(text).classes("lc-empty-text")


def caption(text: str) -> None:
    ui.label(text).classes("lc-caption")


def note(text: str) -> None:
    ui.label(text).classes("lc-note")


def cited(bibliography: Bibliography, key: str) -> None:
    entry = bibliography.get(key, {})
    ui.label(citation(bibliography, key))
    if not entry:
        note(f"not in {defaults.BIB_FILENAME}")
    if entry.get("doi"):
        ui.link("DOI", f"https://doi.org/{entry['doi']}", new_tab=True)
    if entry.get("url"):
        ui.link("Link", entry["url"], new_tab=True)


decimals = 2  # Decimal places of the numbers in tables; the Settings page sets it.


def set_decimals(places: int) -> None:
    global decimals
    decimals = places


def fmt(value: float | None, digits: int | None = None) -> str:
    return "" if value is None else f"{value:.{decimals if digits is None else digits}f}"


def p_value(p: float | None) -> str:
    if p is None:
        return ""
    return "< .001" if p < 0.001 else f"{p:.3f}".replace("0.", ".", 1)


def apa(value: float | None) -> str:
    # Values bounded by 1 drop the leading zero.
    if value is None:
        return ""
    return fmt(value).replace("0.", ".", 1)


def as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def sorted_waves(waves: Iterable[str]) -> list[str]:
    return sorted(set(waves), key=wave_order)


def split_location(location: str) -> tuple[str, int | None]:
    found = LINE_SUFFIX.search(location)
    return (location[: found.start()], int(found.group(1))) if found else (location, None)


def without_line(location: str) -> str:
    return LINE_SUFFIX.sub("", location)


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    else:
        subprocess.run(["xdg-open", str(path)], check=True)


def command(text: str) -> None:
    # A command to type somewhere else, with a button that copies it.
    with ui.row().classes("lc-command w-full items-center no-wrap gap-2"):
        ui.label(text).classes("grow min-w-0 font-mono")
        ui.button(icon="content_copy", on_click=lambda: copy_command(text)).props(
            "flat round dense size=sm"
        ).tooltip("Copy")


def copy_command(text: str) -> None:
    ui.clipboard.write(text)
    ui.notify("Copied")


def code_tabs(code: dict[str, str]) -> None:
    with ui.tabs().props("dense no-caps align=left") as tabs:
        ui.tab("r", label="R")
        ui.tab("python", label="Python")
    with ui.tab_panels(tabs, value="r").classes("w-full"):
        with ui.tab_panel("r").classes("p-0"):
            ui.code(code["r"], language="r").classes("w-full")
        with ui.tab_panel("python").classes("p-0"):
            ui.code(code["python"], language="python").classes("w-full")
