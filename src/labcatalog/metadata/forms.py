import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

from ruamel.yaml.comments import CommentedMap

from labcatalog import defaults
from labcatalog.config import ProjectConfig
from labcatalog.exceptions import EditError, MetadataError
from labcatalog.metadata import records
from labcatalog.metadata.bibliography import load_bibliography
from labcatalog.metadata.completeness import DEMOGRAPHICS, QUESTIONNAIRE
from labcatalog.metadata.records import Column, Table
from labcatalog.project import bib_path, load_config
from labcatalog.stats.summary import wave_order

ABOUT = Table(
    "About",
    (
        Column("id", "ID"),
        Column("name", "Name"),
        Column("abbreviation", "Abbreviation"),
        Column("kind", "Kind", default=QUESTIONNAIRE),
        Column("construct_name", "Construct"),
        Column("description", "Description"),
        Column("instructions", "Instructions"),
        Column("default_response_set", "Default response set"),
        Column("license", "License"),
        Column("items_public", "Items can be shared", "bool", default=False),
        Column("sensitive", "Sensitive", "bool", default=False),
    ),
    single=True,
)
REFERENCES = Table("References", (Column("key", "Reference"), Column("pdf", "PDF")))
NUMBERED = re.compile(r"(.*?)(\d+)")
# Columns that name a response set, by section.
SET_REFERENCES = {
    "response_sets": ("id",),
    "about": ("default_response_set",),
    "items": ("response_set",),
}


@dataclass(frozen=True)
class Section:
    key: str
    table: Table
    # Values to pick from, by column key; typing another value is still allowed.
    options: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Columns on each entry's line; the rest open below it.
    primary: tuple[str, ...] = ()
    # Columns a new entry copies from the one above it.
    carried: tuple[str, ...] = ()
    # Columns shown but not changed here, such as an ID the file name repeats.
    fixed: tuple[str, ...] = ()
    # What one entry is called, for the Add button.
    noun: str = "row"
    # Values to pick from that follow another column of the row: column to (that column, its
    # value to the values).
    follows: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = field(default_factory=dict)

    def options_for(self, row: dict, key: str) -> tuple[str, ...]:
        if key in self.follows:
            driver, values = self.follows[key]
            found = values.get(row.get(driver), ())
            if found:
                return found
        return self.options.get(key, ())


def sections(root: Path, relative: str, text: str) -> list[Section]:
    path = PurePosixPath(relative)
    if path.suffix not in defaults.YAML_SUFFIXES:
        return []
    config = loaded_config(root)
    tables = records.tables_for(relative, config.custom_fields if config else [])
    data = records.load(text)
    if path.name == defaults.CONFIG_FILENAME:
        return config_sections(config, tables)
    if path.parent.name in (defaults.INSTRUMENTS_DIR, defaults.DRAFTS_DIR):
        return instrument_sections(root, config, tables, data)
    if path.parent.name == defaults.STUDIES_DIR:
        return study_sections(root, config, tables, text)
    return []


def loaded_config(root: Path) -> ProjectConfig | None:
    # The page still edits a project whose settings do not load, without the lists to pick from.
    try:
        return load_config(root)
    except MetadataError:
        return None


def instrument_sections(
    root: Path, config: ProjectConfig | None, tables: dict[str, Table], data: CommentedMap
) -> list[Section]:
    sets = ids(data.get("response_sets"))
    kinds = (QUESTIONNAIRE, DEMOGRAPHICS, *(config.vocab.modalities if config else ()))
    keys = tuple(load_bibliography(bib_path(config, root), root, [])) if config else ()
    found = [
        Section(
            "about",
            ABOUT,
            {"kind": tuple(dict.fromkeys(kinds)), "default_response_set": sets},
            fixed=("id",),
        ),
        Section("response_sets", tables["response_sets"], noun="response set"),
        Section(
            "items",
            tables["items"],
            {"response_set": sets, "subscales": ids(data.get("scores"))},
            primary=("id", "text", "response_set", "reverse"),
            carried=("type", "response_set"),
            noun="item",
        ),
        Section(
            "scores",
            tables["scores"],
            {"items": ids(data.get("items"))},
            primary=("id", "label", "method", "items"),
            carried=("method",),
            noun="score",
        ),
        Section("references", REFERENCES, {"key": keys}, primary=("key", "pdf"), noun="reference"),
    ]
    if records.CUSTOM in tables:
        found.append(Section(records.CUSTOM, tables[records.CUSTOM]))
    return found


def study_sections(
    root: Path, config: ProjectConfig | None, tables: dict[str, Table], text: str
) -> list[Section]:
    instruments = tuple(sorted(p.stem for p in (root / defaults.INSTRUMENTS_DIR).glob("*.yaml")))
    datasets = tuple(d.name for d in config.datasets) if config else ()
    contents = instrument_contents(root)
    entries = {
        records.entry_label(n, entry): entry
        for n, entry in enumerate(records.load(text).get("administrations") or [])
    }

    def per_entry(values: Callable[[CommentedMap], tuple[str, ...]]):
        return ("administration", {label: values(entry) for label, entry in entries.items()})

    def instrument(entry: CommentedMap) -> CommentedMap:
        return contents.get(str(entry.get("instrument")), CommentedMap())

    return [
        Section(
            "administrations",
            tables["administrations"],
            {
                "instrument": instruments,
                "datasets": datasets,
                "target": tuple(config.vocab.targets) if config else (),
            },
            primary=("instrument", "datasets", "target"),
            noun="administration",
        ),
        Section(
            "overrides",
            records.with_entries(tables["overrides"], text),
            {"dataset": datasets},
            primary=("administration", "item", "dataset", "dropped"),
            noun="change",
            follows={
                "item": per_entry(lambda e: ids(instrument(e).get("items"))),
                "response_set": per_entry(lambda e: ids(instrument(e).get("response_sets"))),
                "dataset": per_entry(lambda e: tuple(str(d) for d in e.get("datasets") or ())),
            },
        ),
    ]


def instrument_contents(root: Path) -> dict[str, CommentedMap]:
    # A file that does not read yet offers nothing to pick; the study form still opens.
    found = {}
    for path in sorted((root / defaults.INSTRUMENTS_DIR).glob("*.yaml")):
        try:
            data = records.load(path.read_text(encoding="utf-8"))
        except EditError:
            continue
        found[str(data.get("id", path.stem))] = data
    return found


def config_sections(config: ProjectConfig | None, tables: dict[str, Table]) -> list[Section]:
    options = {}
    if config:
        waves = {w for study in config.studies.values() for w in study.waves}
        options = {
            "modality": tuple(config.vocab.modalities),
            "study": tuple(config.studies),
            "wave": tuple(sorted(waves, key=wave_order)),
            "reporter": tuple(config.vocab.reporters),
        }
    return [
        Section(
            "datasets",
            tables["datasets"],
            options,
            primary=("name", "study", "wave", "reporter", "modality"),
            carried=("study", "wave", "modality", "source"),
            noun="dataset",
        )
    ]


def rename_set(
    sections: list[Section], rows: dict[str, list[dict]], old: str, new: str
) -> list[Section]:
    for key, columns in SET_REFERENCES.items():
        for row in rows.get(key, ()):
            for column in columns:
                if row.get(column) == old:
                    row[column] = new
    return [
        replace(
            section,
            options={
                key: tuple(new if o == old else o for o in options)
                if key in SET_REFERENCES.get(section.key, ())
                else options
                for key, options in section.options.items()
            },
        )
        for section in sections
    ]


def ids(entries: list | None) -> tuple[str, ...]:
    return tuple(str(entry.get("id")) for entry in entries or [] if entry.get("id") is not None)


def next_id(taken: list[str], stem: str) -> str:
    # The next of a numbered run such as ems_1, ems_2; else the stem numbered from 1.
    prefix, n = f"{stem}_", 1
    for last in reversed(taken):
        found = NUMBERED.fullmatch(last)
        if found:
            prefix, n = found.group(1), int(found.group(2)) + 1
            break
    while f"{prefix}{n}" in taken:
        n += 1
    return f"{prefix}{n}"
