import csv
from dataclasses import dataclass
from pathlib import Path

from labcatalog import defaults
from labcatalog.annex import fetch_advice, is_placeholder
from labcatalog.issues import Issue

MAP_COLUMNS = ("column", "instrument", "item")


@dataclass
class MapEntry:
    column: str
    instrument: str | None
    item: str | None
    line: int

    @property
    def score_id(self) -> str | None:
        if self.item and self.item.startswith(defaults.SCORE_PREFIX):
            return self.item.removeprefix(defaults.SCORE_PREFIX)
        return None


def load_variable_map(path: Path, root: Path, issues: list[Issue]) -> list[MapEntry]:
    location = path.relative_to(root).as_posix()
    if is_placeholder(path):
        issues.append(map_issue("not_downloaded", fetch_advice(path), location))
        return []
    try:
        # utf-8-sig accepts the byte-order mark that Excel writes for "CSV UTF-8".
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        issues.append(
            map_issue("map_encoding", "not UTF-8; in Excel save as 'CSV UTF-8'", location)
        )
        return []
    reader = csv.DictReader(text.splitlines())
    absent = [name for name in MAP_COLUMNS if name not in (reader.fieldnames or [])]
    if absent:
        expected = ", ".join(MAP_COLUMNS)
        issues.append(map_issue("map_header", f"header must contain {expected}", location))
        return []

    entries = []
    for line, row in enumerate(reader, start=2):
        column = (row["column"] or "").strip()
        instrument = (row["instrument"] or "").strip() or None
        item = (row["item"] or "").strip() or None
        where = f"{location}:{line}"
        if not (column or instrument or item):
            continue
        if not column:
            issues.append(map_issue("map_row", "column is empty", where))
        elif bool(instrument) != bool(item):
            issues.append(
                map_issue("map_row", "instrument and item must be filled together", where)
            )
        else:
            entries.append(MapEntry(column=column, instrument=instrument, item=item, line=line))
    return entries


def map_issue(code: str, message: str, location: str) -> Issue:
    return Issue(level="error", code=code, message=message, location=location)
