import io
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import PurePosixPath
from typing import Any, Literal

import yaml
from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import SingleQuotedScalarString
from ruamel.yaml.tokens import CommentToken

from labcatalog import defaults
from labcatalog.config import CustomFieldDef
from labcatalog.exceptions import EditError

Kind = Literal["text", "bool", "number", "list", "choice", "value", "date"]
# Where each list's rows came from in the file; new rows have none.
ORIGIN = "_row"
# Joins the keys of a value nested in each entry, as custom:topics for custom: {topics: ...}.
NESTED = ":"
CUSTOM = "custom"
FIELD_KINDS: dict[str, Kind] = {
    "text": "text",
    "number": "number",
    "date": "date",
    "choice": "choice",
    "tags": "list",
}


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: Kind = "text"
    choices: tuple[str, ...] = ()
    # The value the schema assumes when the key is left out.
    default: Any = None


@dataclass(frozen=True)
class Table:
    label: str
    columns: tuple[Column, ...]
    # Set when rows come from a list inside each entry; the first column is then the entry's key.
    inner: str | None = None
    # One row for the whole file rather than one per entry of a list.
    single: bool = False
    # Set when rows come from a list inside each entry of this list, which rows only point to.
    parent: str | None = None


ITEMS = Table(
    "Items",
    (
        Column("id", "ID"),
        Column("text", "Text"),
        Column("label", "Label"),
        Column("type", "Type", "choice", ("choice", "number", "text"), "choice"),
        Column("response_set", "Response set"),
        Column("reverse", "Reverse", "bool", default=False),
        Column("subscales", "Subscales", "list"),
        Column("min", "Min", "number"),
        Column("max", "Max", "number"),
    ),
)
SCORES = Table(
    "Scores",
    (
        Column("id", "ID"),
        Column("label", "Label"),
        Column("method", "Method", "choice", ("sum", "mean")),
        Column("items", "Items", "list"),
        Column("missing_rule", "Missing", "choice", ("complete", "prorate", "zero"), "complete"),
        Column("min_valid", "Min answered", "number"),
    ),
)
OPTIONS = Table(
    "Response sets",
    (Column("id", "Set"), Column("value", "Value", "value"), Column("label", "Label")),
    inner="options",
)
ADMINISTRATIONS = Table(
    "Administrations",
    (
        Column("instrument", "Instrument"),
        Column("datasets", "Datasets", "list"),
        Column("target", "Target"),
        Column("abbreviation", "Abbreviation"),
        Column("reversed_in_data", "Reversed in data", "bool", default=False),
    ),
)
OVERRIDES = Table(
    "Overrides",
    (
        Column("administration", "Administration", "choice"),
        Column("item", "Item"),
        Column("dataset", "Dataset"),
        Column("text", "Text"),
        Column("response_set", "Response set"),
        Column("dropped", "Dropped", "bool", default=False),
    ),
    inner="overrides",
    parent="administrations",
)
DATASETS = Table(
    "Datasets",
    (
        Column("name", "Name"),
        Column("modality", "Modality"),
        Column("study", "Study"),
        Column("wave", "Wave"),
        Column("reporter", "Reporter"),
        Column("source", "Source", "choice", ("csv", "folder")),
        Column("path", "Path"),
        Column("files", "Files"),
        Column("id_column", "ID column"),
        Column("group_column", "Group column"),
        Column("date_column", "Date column"),
        Column("snapshot_date", "Snapshot date"),
    ),
)
INSTRUMENT_TABLES = {"items": ITEMS, "scores": SCORES, "response_sets": OPTIONS}
TABLES = {
    defaults.INSTRUMENTS_DIR: INSTRUMENT_TABLES,
    defaults.DRAFTS_DIR: INSTRUMENT_TABLES,
    defaults.STUDIES_DIR: {"administrations": ADMINISTRATIONS, "overrides": OVERRIDES},
    "": {"datasets": DATASETS},
}


# The custom fields that apply to each table's rows.
OWNERS = {"scores": "score", "administrations": "administration", "datasets": "dataset"}


def tables_for(relative: str, fields: Iterable[CustomFieldDef] = ()) -> dict[str, Table]:
    path = PurePosixPath(relative)
    if path.suffix not in defaults.YAML_SUFFIXES:
        return {}
    base = TABLES[""] if path.name == defaults.CONFIG_FILENAME else TABLES.get(path.parent.name, {})
    columns = {owner: [] for owner in [*OWNERS.values(), "instrument"]}
    for field in fields:
        columns[field.applies_to].append(custom_column(field))
    tables = {
        key: replace(table, columns=table.columns + tuple(columns[OWNERS[key]]))
        if key in OWNERS
        else table
        for key, table in base.items()
    }
    if base is INSTRUMENT_TABLES and columns["instrument"]:
        tables[CUSTOM] = Table("Custom fields", tuple(columns["instrument"]), single=True)
    return tables


def custom_column(field: CustomFieldDef) -> Column:
    kind = FIELD_KINDS[field.type]
    choices = tuple(field.choices or ())
    # An empty choice clears the field.
    return Column(
        f"{CUSTOM}{NESTED}{field.name}",
        field.label or field.name,
        kind,
        ("", *choices) if kind == "choice" else choices,
    )


def with_entries(table: Table, text: str) -> Table:
    # The entries rows can point to are the file's own, so they are read from it.
    if table.parent is None:
        return table
    entries = load(text).get(table.parent) or []
    first, *rest = table.columns
    choices = tuple(entry_label(n, entry) for n, entry in enumerate(entries))
    return replace(table, columns=(replace(first, choices=choices), *rest))


def entry_label(n: int, entry: CommentedMap) -> str:
    return f"{n + 1}: {entry.get('instrument')}"


def load(text: str) -> CommentedMap:
    try:
        return round_trip().load(text) or CommentedMap()
    except YAMLError as err:
        raise EditError(f"The file is not valid YAML; fix it as text first. {err}") from None


def dumped(data: CommentedMap) -> str:
    out = io.StringIO()
    round_trip().dump(data, out)
    return out.getvalue()


def take_tail(node: CommentedMap | CommentedSeq) -> str:
    # The lines after the last value under node, such as the next section's heading comment.
    holder, key = tail_slot(node)
    if key is None:
        text = "".join(token.value for token in holder.ca.end)
        holder.ca.end = []
        return text
    slot = holder.ca.items.get(key)
    if not slot or slot[2] is None:
        return ""
    # A comment on the value's own line stays with it.
    own, _, text = slot[2].value.partition("\n")
    slot[2] = CommentToken(own + "\n", CommentMark(0), None) if own else None
    return text


def put_tail(node: CommentedMap | CommentedSeq, text: str) -> None:
    if not text:
        return
    holder, key = tail_slot(node)
    if key is None:
        holder.ca.end = [CommentToken(text, CommentMark(0), None)]
        return
    slot = holder.ca.items.setdefault(key, [None, None, None, None])
    own = slot[2].value if slot[2] is not None else "\n"
    slot[2] = CommentToken(own + text, CommentMark(0), None)


def tail_slot(node: CommentedMap | CommentedSeq) -> tuple[Any, Any]:
    # Where ruamel keeps what follows a subtree: after its last scalar, or at the end of a list.
    while True:
        last = node[-1] if isinstance(node, CommentedSeq) and node else None
        if isinstance(node, CommentedMap) and node:
            key = list(node)[-1]
            last = node[key]
        if not isinstance(last, (CommentedMap, CommentedSeq)) or not last or last.fa.flow_style():
            if isinstance(node, CommentedSeq):
                return node, None
            return node, (key if node else None)
        node = last


def round_trip() -> YAML:
    # The layout labcatalog writes, so untouched lines come back as they were.
    loader = YAML()
    loader.preserve_quotes = True
    loader.width = 4096
    loader.indent(mapping=2, sequence=4, offset=2)
    return loader


def read_rows(text: str, key: str, table: Table) -> list[dict[str, Any]]:
    data = load(text)
    if table.parent:
        first, *columns = table.columns
        return [
            {ORIGIN: [n, m], first.key: entry_label(n, entry)} | cells(part, columns, key)
            for n, entry in enumerate(data.get(table.parent) or [])
            for m, part in enumerate(entry.get(table.inner) or [])
        ]
    if table.single:
        return [{ORIGIN: 0} | cells(data, table.columns, key)]
    entries = data.get(key) or []
    if table.inner is None:
        return [{ORIGIN: n} | cells(entry, table.columns, key) for n, entry in enumerate(entries)]
    group, *columns = table.columns
    rows = []
    for n, entry in enumerate(entries):
        name = shown(entry.get(group.key), group)
        if not entry.get(table.inner):
            raise EditError(f"{key}: {name} has no {table.inner}; edit this file as text")
        for m, part in enumerate(entry[table.inner]):
            rows.append({ORIGIN: [n, m], group.key: name} | cells(part, columns, key))
    return rows


def cells(entry: CommentedMap, columns: Iterable[Column], key: str) -> dict[str, Any]:
    row = {}
    for column in columns:
        value = lookup(entry, column)
        if isinstance(value, dict):
            raise EditError(f"{key} has {column.key} written per language; edit this file as text")
        row[column.key] = shown(value, column)
    return row


def write_rows(text: str, key: str, table: Table, rows: list[dict]) -> str:
    loader = round_trip()
    data = loader.load(text) or CommentedMap()
    if table.single:
        fill(data, table.columns, rows[0])
    elif table.parent:
        write_nested(data, table, rows)
    elif table.inner is None:
        origins = [row.get(ORIGIN) for row in rows]
        for row, entry in zip(rows, place(data, key, origins), strict=True):
            fill(entry, table.columns, row)
    else:
        write_groups(data, key, table, rows)
    out = io.StringIO()
    loader.dump(data, out)
    return out.getvalue()


def write_groups(data: CommentedMap, key: str, table: Table, rows: list[dict]) -> None:
    group, *columns = table.columns
    members: dict[str, list[dict]] = {}
    for row in rows:
        name = stored(row.get(group.key), group)
        if name is None:
            raise EditError(f"{group.label}: every row needs one")
        members.setdefault(name, []).append(row)
    names = [str(entry.get(group.key)) for entry in data.get(key) or []]
    # An entry stays with the rows that still carry its name, else with rows that came from it.
    owner: dict[str, int | None] = {}
    for name, found in members.items():
        owner[name] = next((n for n in sources(found) if names[n] == name), None)
    for name, found in members.items():
        if owner[name] is None:
            owner[name] = next((n for n in sources(found) if n not in owner.values()), None)
    entries = place(data, key, list(owner.values()), flow=False)
    for (name, found), entry in zip(members.items(), entries, strict=True):
        update(entry, group, name)
        origins = [
            r[ORIGIN][1] if r.get(ORIGIN) and r[ORIGIN][0] == owner[name] else None for r in found
        ]
        for row, part in zip(found, place(entry, table.inner, origins), strict=True):
            fill(part, columns, row)


def write_nested(data: CommentedMap, table: Table, rows: list[dict]) -> None:
    entries = data.get(table.parent) or []
    first, *columns = table.columns
    labels = {entry_label(n, entry): n for n, entry in enumerate(entries)}
    members: dict[int, list[dict]] = {n: [] for n in range(len(entries))}
    for row in rows:
        if row.get(first.key) not in labels:
            raise EditError(f"{first.label}: choose one for every row")
        members[labels[row[first.key]]].append(row)
    for n, entry in enumerate(entries):
        found = members[n]
        if not found:
            entry.pop(table.inner, None)
            continue
        origins = [r[ORIGIN][1] if r.get(ORIGIN) and r[ORIGIN][0] == n else None for r in found]
        for row, part in zip(found, place(entry, table.inner, origins), strict=True):
            fill(part, columns, row)


def sources(rows: list[dict]) -> list[int]:
    return [row[ORIGIN][0] for row in rows if row.get(ORIGIN)]


def place(parent: CommentedMap, key: str, origins: list[int | None], flow: bool = True) -> list:
    old = parent.get(key)
    if not old:
        # An empty [] would keep new rows on its one line.
        old = parent[key] = CommentedSeq()
    entries = [None if n is None else old[n] for n in origins]
    # Rows keep their order, so dropping and inserting in place keeps comments between them.
    for n in reversed(range(len(old))):
        if n not in origins:
            del old[n]
    for n, entry in enumerate(entries):
        if entry is None:
            entries[n] = CommentedMap()
            if flow:
                # One line per entry, as labcatalog and its example write them.
                entries[n].fa.set_flow_style()
            old.insert(n, entries[n])
    # Rows dragged into another order move their entries; otherwise the list is left as it was.
    if [id(e) for e in old] != [id(e) for e in entries]:
        old.clear()
        old.extend(entries)
    return entries


def fill(entry: CommentedMap, columns: Iterable[Column], row: dict) -> None:
    for column in columns:
        update(entry, column, row.get(column.key))


def lookup(entry: CommentedMap, column: Column) -> Any:
    *outer, name = column.key.split(NESTED)
    for part in outer:
        entry = entry.get(part) or {}
    return entry.get(name)


def update(entry: CommentedMap, column: Column, cell: Any) -> None:
    # Unchanged cells leave the file alone, so 1 stays 1 rather than becoming '1'.
    if shown(lookup(entry, column), column) == shown(stored(cell, column), column):
        return
    value = stored(cell, column)
    *outer, name = column.key.split(NESTED)
    parents = [entry]
    for part in outer:
        if not isinstance(parents[-1].get(part), dict):
            parents[-1][part] = CommentedMap()
        parents.append(parents[-1][part])
    holder = parents[-1]
    if value is None or value == column.default:
        holder.pop(name, None)
        # A nested map left empty goes too, so no custom: {} stays behind.
        for parent, part in reversed(list(zip(parents[:-1], outer, strict=True))):
            if not parent[part]:
                del parent[part]
    elif isinstance(value, list):
        holder[name] = [as_text(v) for v in value]
    else:
        holder[name] = as_text(value)


def as_text(value: Any) -> Any:
    # Projects load as YAML 1.1, where a bare Yes or 1:30 is not text.
    if not isinstance(value, str):
        return value
    try:
        plain = yaml.safe_load(value) == value
    except yaml.YAMLError:
        plain = False
    return value if plain else SingleQuotedScalarString(value)


def shown(value: Any, column: Column) -> Any:
    if column.kind == "bool":
        return bool(value) if value is not None else bool(column.default)
    if column.kind == "list":
        return ", ".join(str(v) for v in value or [])
    if column.kind in ("value", "date"):
        return "" if value is None else str(value)
    if value is None:
        return "" if column.default is None else column.default
    return value if column.kind == "number" else str(value)


def stored(cell: Any, column: Column) -> Any:
    if column.kind == "bool":
        return bool(cell)
    text = "" if cell is None else str(cell).strip()
    if column.kind == "list":
        parts = [part.strip() for part in text.split(",") if part.strip()]
        undeclared = [part for part in parts if column.choices and part not in column.choices]
        if undeclared:
            raise EditError(
                f"{column.label}: {', '.join(undeclared)} not declared in custom_fields"
            )
        return parts or None
    if not text:
        return None
    if column.kind == "date":
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise EditError(f"{column.label}: '{text}' is not a date such as 2026-01-31") from None
    if column.kind == "number":
        try:
            number = float(text)
        except ValueError:
            raise EditError(f"{column.label}: '{text}' is not a number") from None
        return int(number) if number.is_integer() else number
    if column.kind == "value":
        return scalar(text)
    return text


def scalar(text: str) -> int | float | str:
    # Only numbers written as YAML writes them count, so '01' stays text.
    for kind in (int, float):
        try:
            if str(kind(text)) == text:
                return kind(text)
        except ValueError:
            pass
    return text
