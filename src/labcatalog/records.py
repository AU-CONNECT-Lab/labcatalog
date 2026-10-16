import io
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.exceptions import EditError

Kind = Literal["text", "bool", "number", "list", "choice"]
# Where each list's rows came from in the file; new rows have none.
ORIGIN = "_row"


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: Kind = "text"
    choices: tuple[str, ...] = ()
    # The value the schema assumes when the key is left out.
    default: Any = None


ITEMS = (
    Column("id", "ID"),
    Column("text", "Text"),
    Column("type", "Type", "choice", ("choice", "number", "text"), "choice"),
    Column("response_set", "Options"),
    Column("reverse", "Reverse", "bool", default=False),
    Column("subscales", "Subscales", "list"),
    Column("min", "Min", "number"),
    Column("max", "Max", "number"),
)
SCORES = (
    Column("id", "ID"),
    Column("label", "Label"),
    Column("method", "Method", "choice", ("sum", "mean")),
    Column("items", "Items", "list"),
    Column("missing_rule", "Missing", "choice", ("complete", "prorate", "zero"), "complete"),
    Column("min_valid", "Min answered", "number"),
)
DATASETS = (
    Column("name", "Name"),
    Column("modality", "Modality"),
    Column("study", "Study"),
    Column("wave", "Wave"),
    Column("reporter", "Reporter"),
    Column("source", "Source", "choice", ("csv",)),
    Column("path", "Path"),
    Column("id_column", "ID column"),
    Column("group_column", "Group column"),
    Column("date_column", "Date column"),
    Column("snapshot_date", "Snapshot date"),
)
TABLES = {
    defaults.INSTRUMENTS_DIR: {"items": ITEMS, "scores": SCORES},
    "": {"datasets": DATASETS},
}


def tables_for(relative: str) -> dict[str, tuple[Column, ...]]:
    path = PurePosixPath(relative)
    if path.suffix not in defaults.YAML_SUFFIXES:
        return {}
    if path.name == defaults.CONFIG_FILENAME:
        return TABLES[""]
    return TABLES.get(path.parent.name, {})


def round_trip() -> YAML:
    # The layout labcatalog writes, so untouched lines come back as they were.
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def read_rows(text: str, key: str, columns: tuple[Column, ...]) -> list[dict[str, Any]]:
    data = round_trip().load(text) or {}
    rows = []
    for n, entry in enumerate(data.get(key) or []):
        row = {ORIGIN: n}
        for column in columns:
            value = entry.get(column.key)
            if isinstance(value, dict):
                raise EditError(
                    f"{key} has {column.key} written per language; edit this file as text"
                )
            row[column.key] = shown(value, column)
        rows.append(row)
    return rows


def write_rows(text: str, key: str, columns: tuple[Column, ...], rows: list[dict]) -> str:
    yaml = round_trip()
    data = yaml.load(text) or CommentedMap()
    old = data.get(key)
    if not old:
        # An empty [] would keep new rows on its one line.
        old = data[key] = CommentedSeq()
    # Rows keep their order, so dropping and appending in place keeps comments between them.
    kept = {row[ORIGIN] for row in rows if isinstance(row.get(ORIGIN), int)}
    targets = [old[row[ORIGIN]] if row.get(ORIGIN) in kept else None for row in rows]
    for n in reversed(range(len(old))):
        if n not in kept:
            del old[n]
    for row, entry in zip(rows, targets, strict=True):
        if entry is None:
            entry = CommentedMap()
            # One line per entry, as labcatalog and its example write them.
            entry.fa.set_flow_style()
            old.append(entry)
        for column in columns:
            update(entry, column, row.get(column.key))
    out = io.StringIO()
    yaml.dump(data, out)
    return out.getvalue()


def update(entry: CommentedMap, column: Column, cell: Any) -> None:
    # Unchanged cells leave the file alone, so 1 stays 1 rather than becoming '1'.
    if shown(entry.get(column.key), column) == shown(stored(cell, column), column):
        return
    value = stored(cell, column)
    if value is None or value == column.default:
        entry.pop(column.key, None)
    else:
        entry[column.key] = value


def shown(value: Any, column: Column) -> Any:
    if column.kind == "bool":
        return bool(value) if value is not None else bool(column.default)
    if column.kind == "list":
        return ", ".join(str(v) for v in value or [])
    if value is None:
        return "" if column.default is None else column.default
    return value if column.kind == "number" else str(value)


def stored(cell: Any, column: Column) -> Any:
    if column.kind == "bool":
        return bool(cell)
    text = "" if cell is None else str(cell).strip()
    if column.kind == "list":
        return [part.strip() for part in text.split(",") if part.strip()] or None
    if not text:
        return None
    if column.kind == "number":
        try:
            number = float(text)
        except ValueError:
            raise EditError(f"{column.label}: '{text}' is not a number") from None
        return int(number) if number.is_integer() else number
    return text
