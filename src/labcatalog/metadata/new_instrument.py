import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.codebook.core import MODELINE, read_data
from labcatalog.config import dataset_by_name
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing, records
from labcatalog.metadata.changes import Change
from labcatalog.metadata.completeness import QUESTIONNAIRE, gaps
from labcatalog.metadata.fixes import closest, free_columns, map_rows
from labcatalog.metadata.studies import place_key
from labcatalog.metadata.varmap import MAP_COLUMNS
from labcatalog.project import Project
from labcatalog.schema import Instrument

STEPS = ("about", "options", "items", "scores", "given", "check")
# The step where each gap of the completeness check is filled in.
GAP_STEPS = {"items": "items", "scores": "scores"}
ABOUT = ("name", "abbreviation", "kind", "construct_name", "description", "license")
# The instrument file's keys in the order labcatalog writes them.
ORDER = tuple(Instrument.model_fields)
# Questionnaires often mark reversed items this way, so a pasted line keeps that.
REVERSED = re.compile(r"\s*\(R\)\s*$", re.IGNORECASE)


@dataclass
class Draft:
    id: str
    about: dict[str, str] = field(default_factory=lambda: {"kind": QUESTIONNAIRE})
    # Rows as the Edit page's tables hold them, so the same writer puts them in the file.
    options: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    scores: list[dict[str, Any]] = field(default_factory=list)
    default_set: str = ""
    references: list[str] = field(default_factory=list)
    # New datasets it is given in, each with the data column of every item found there.
    given: dict[str, dict[str, str]] = field(default_factory=dict)
    # The file being completed; None for a new instrument.
    path: str | None = None


def existing(project: Project, instrument_id: str) -> Draft:
    path = project.instrument_files[instrument_id]
    text = editing.open_file(project.root, path).text
    data = records.load(text)
    tables = records.INSTRUMENT_TABLES
    return Draft(
        id=instrument_id,
        about={k: str(data[k]) for k in ABOUT if data.get(k) is not None},
        options=records.read_rows(text, "response_sets", tables["response_sets"]),
        items=records.read_rows(text, "items", tables["items"]),
        scores=records.read_rows(text, "scores", tables["scores"]),
        default_set=str(data.get("default_response_set") or ""),
        references=[str(r["key"]) for r in data.get("references") or []],
        path=path,
    )


def first_gap(project: Project, instrument_id: str) -> str:
    found = [GAP_STEPS.get(gap, "about") for gap in gaps(project.instruments[instrument_id])]
    return min(found, key=STEPS.index, default="about")


def check_about(project: Project, draft: Draft) -> None:
    if draft.path is None:
        editing.free_instrument_path(project.root, draft.id)
        if draft.id in project.instruments:
            raise EditError(f"An instrument called {draft.id} already exists")
    if not draft.about.get("name", "").strip():
        raise EditError("Name: fill it in")


def copy_options(project: Project, instrument_id: str) -> list[dict[str, Any]]:
    return [
        {"id": s.id, "value": str(o.value), "label": o.label}
        for s in project.instruments[instrument_id].response_sets
        for o in s.options
    ]


def prefix(draft: Draft) -> str:
    # Item IDs start with the abbreviation, as in the example project.
    short = re.sub(r"[^a-z0-9]+", "_", draft.about.get("abbreviation", "").lower()).strip("_")
    return short if editing.NEW_ID.fullmatch(short) else draft.id


def items_from_lines(draft: Draft, text: str) -> list[dict[str, Any]]:
    taken = {str(row["id"]) for row in draft.items}
    found, n = [], len(draft.items)
    for line in text.splitlines():
        if not line.strip():
            continue
        n += 1
        while f"{prefix(draft)}_{n}" in taken:
            n += 1
        reverse = bool(REVERSED.search(line))
        found.append(
            {
                "id": f"{prefix(draft)}_{n}",
                "text": REVERSED.sub("", line).strip(),
                "reverse": reverse,
            }
        )
    return found


def suggest_total(draft: Draft) -> dict[str, Any]:
    scored = [str(row["id"]) for row in draft.items if row.get("type", "choice") == "choice"]
    return {
        "id": f"{prefix(draft)}_total",
        "label": "Total score",
        "method": "sum",
        "items": ", ".join(scored),
    }


def given_in(project: Project, instrument_id: str) -> list[str]:
    return [
        name
        for content in project.studies.values()
        for a in content.administrations
        if a.instrument == instrument_id
        for name in a.datasets
    ]


def free_columns_of(project: Project, dataset: str) -> list[str]:
    config = dataset_by_name(project.config, dataset)
    return free_columns(project, dataset, [str(c) for c in read_data(project, config).columns])


def guess_columns(project: Project, dataset: str, items: list[str]) -> dict[str, str]:
    # Data columns the map does not list yet, by name: the item's ID, then with a wave suffix.
    left = free_columns_of(project, dataset)
    found = {}
    for item in items:
        column = next((c for c in left if c == item), None)
        column = column or next((c for c in left if c.startswith(f"{item}_")), None)
        column = column or closest(item, left)
        if column:
            found[item] = column
            left.remove(column)
    return found


def changes(project: Project, draft: Draft) -> list[Change]:
    return [instrument_change(project, draft), *given_changes(project, draft)]


def instrument_change(project: Project, draft: Draft) -> Change:
    opened = editing.open_file(project.root, draft.path) if draft.path else None
    text = opened.text if opened else starting_text(draft.id)
    tables = records.INSTRUMENT_TABLES
    # Items on the default set need not name it.
    items = [
        row | {"response_set": ""} if row.get("response_set") == draft.default_set else row
        for row in draft.items
    ]
    for key, rows in (("response_sets", draft.options), ("items", items), ("scores", draft.scores)):
        # An empty table adds no empty list to a file that has none.
        if rows or key in records.load(text):
            text = records.write_rows(text, key, tables[key], rows)
    data = records.load(text)
    for key in ABOUT:
        value = draft.about.get(key, "").strip() or None
        # The default kind is written only where the file already had it.
        if key == "kind" and value == QUESTIONNAIRE and key not in data:
            value = None
        put(data, key, value)
    put(data, "default_response_set", draft.default_set or None)
    put(data, "references", references(data, draft.references))
    relative = draft.path or f"{defaults.INSTRUMENTS_DIR}/{draft.id}.yaml"
    return Change(relative, records.dumped(data), opened)


def starting_text(instrument_id: str) -> str:
    # As the Edit page's New instrument writes it, so the lists keep the schema's order.
    lines = [MODELINE.format("instrument"), f"id: {instrument_id}"]
    lines += ["response_sets: []", "items: []", "scores: []"]
    return "\n".join(lines) + "\n"


def put(data: CommentedMap, key: str, value: Any) -> None:
    if value is None:
        data.pop(key, None)
        return
    if isinstance(value, str) and str(data.get(key)) == value:
        return
    if isinstance(value, str):
        value = records.as_text(value)
    # After the nearest key that comes before it in the schema's order.
    before = [k for k in ORDER[: ORDER.index(key)] if k in data]
    place_key(data, key, value, before[-1] if before else "id")


def references(data: CommentedMap, keys: list[str]) -> CommentedSeq | None:
    # A reference kept keeps its PDF; a new one is just its key.
    kept = {str(r["key"]): r for r in data.get("references") or []}
    if list(kept) == keys:
        return data.get("references")
    found = CommentedSeq()
    for key in keys:
        entry = kept.get(key)
        if entry is None:
            entry = CommentedMap(key=key)
            entry.fa.set_flow_style()
        found.append(entry)
    return found or None


def given_changes(project: Project, draft: Draft) -> list[Change]:
    found = []
    for dataset, columns in draft.given.items():
        rows = [(column, draft.id, item) for item, column in columns.items() if column]
        if dataset in project.maps:
            found.append(map_rows(project, dataset, rows))
        else:
            out = io.StringIO()
            csv.writer(out, lineterminator="\n").writerows([MAP_COLUMNS, *rows])
            found.append(Change(f"{defaults.MAPS_DIR}/{dataset}.csv", out.getvalue()))
    studies: dict[str, list[str]] = {}
    for dataset in draft.given:
        studies.setdefault(dataset_by_name(project.config, dataset).study, []).append(dataset)
    found += [administer(project, draft.id, s, names) for s, names in studies.items()]
    return found


def administer(project: Project, instrument_id: str, study: str, datasets: list[str]) -> Change:
    # Added to the study's administration of the instrument, or a new one when it has none.
    relative = project.study_files.get(study, f"{defaults.STUDIES_DIR}/{study}.yaml")
    opened = (
        editing.open_file(project.root, relative) if (project.root / relative).exists() else None
    )
    data = records.load(opened.text if opened else f"{MODELINE.format('study')}\nstudy: {study}\n")
    if not data.get("administrations"):
        data["administrations"] = CommentedSeq()
    entry = next((a for a in data["administrations"] if a["instrument"] == instrument_id), None)
    if entry is None:
        entry = CommentedMap(instrument=instrument_id, datasets=CommentedSeq())
        entry.fa.set_flow_style()
        entry["datasets"].fa.set_flow_style()
        data["administrations"].append(entry)
    entry["datasets"].extend(d for d in datasets if d not in entry["datasets"])
    return Change(relative, records.dumped(data), opened)
