import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from nicegui import ui

from labcatalog.stats import wave_order

LINE_SUFFIX = re.compile(r":\d+$")
ROW_KEY = "_row"


def col(name: str, label: str, *, numeric: bool = False, sortable: bool = True) -> dict:
    align = "right" if numeric else "left"
    return {"name": name, "label": label, "field": name, "align": align, "sortable": sortable}


def table(columns: list[dict], rows: list[dict]) -> ui.table:
    return (
        ui.table(columns=columns, rows=keyed(rows), row_key=ROW_KEY)
        .props("flat bordered dense wrap-cells")
        .classes("w-full")
    )


def keyed(rows: list[dict]) -> list[dict]:
    return [{ROW_KEY: i, **row} for i, row in enumerate(rows)]


def heading(text: str) -> None:
    ui.label(text).classes("text-lg font-medium mt-6")


def note(text: str) -> None:
    ui.label(text).classes("text-grey-7")


def fmt(value: float | None, digits: int = 2) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def as_text(value: object) -> str:
    return ", ".join(as_list(value))


def as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def sorted_waves(waves: Iterable[str]) -> list[str]:
    return sorted(set(waves), key=wave_order)


def location_path(root: Path, location: str) -> Path:
    return root / without_line(location)


def without_line(location: str) -> str:
    return LINE_SUFFIX.sub("", location)


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=True)
    else:
        subprocess.run(["xdg-open", str(path)], check=True)
