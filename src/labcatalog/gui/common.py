import os
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from nicegui import ui

from labcatalog import defaults
from labcatalog.bibliography import Bibliography, citation
from labcatalog.stats import wave_order

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


@contextmanager
def card(title: str, subtitle: str = "") -> Iterator[ui.row]:
    # Yields the header's right-hand row, for controls that belong to the card.
    with ui.card().props("flat").classes("lc-card w-full"):
        with ui.row().classes("w-full items-start no-wrap gap-4"):
            with ui.column().classes("grow gap-0"):
                ui.label(title).classes("lc-card-title")
                if subtitle:
                    ui.label(subtitle).classes("lc-card-subtitle")
            tools = ui.row().classes("items-center no-wrap gap-3")
        yield tools


def section(text: str) -> None:
    ui.label(text).classes("lc-section")


def heading(text: str) -> None:
    ui.label(text).classes("lc-heading")


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


def fmt(value: float | None, digits: int = 2) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def p_value(p: float | None) -> str:
    if p is None:
        return ""
    return "< .001" if p < 0.001 else f"{p:.3f}".replace("0.", ".", 1)


def apa(value: float | None) -> str:
    # Values bounded by 1 drop the leading zero.
    if value is None:
        return ""
    return f"{value:.2f}".replace("0.", ".", 1)


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


def code_tabs(code: dict[str, str]) -> None:
    with ui.tabs().props("dense no-caps align=left") as tabs:
        ui.tab("r", label="R")
        ui.tab("python", label="Python")
    with ui.tab_panels(tabs, value="r").classes("w-full"):
        with ui.tab_panel("r").classes("p-0"):
            ui.code(code["r"], language="r").classes("w-full")
        with ui.tab_panel("python").classes("p-0"):
            ui.code(code["python"], language="python").classes("w-full")
