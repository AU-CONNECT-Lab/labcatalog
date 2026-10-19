import io
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.codebook.core import MODELINE
from labcatalog.config import (
    CustomFieldDef,
    FreedParameter,
    PrepareStep,
    ProjectConfig,
    SavedAnalysis,
)
from labcatalog.exceptions import EditError, MetadataError
from labcatalog.issues import Issue
from labcatalog.metadata import records
from labcatalog.metadata.bibliography import load_bibliography
from labcatalog.metadata.varmap import load_variable_map
from labcatalog.project import bib_path, load_config, load_model
from labcatalog.schema import Instrument, StudyContent

FOLDERS: dict[str, type[BaseModel]] = {
    defaults.INSTRUMENTS_DIR: Instrument,
    defaults.DRAFTS_DIR: Instrument,
    defaults.STUDIES_DIR: StudyContent,
}
NEW_ID = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class Opened:
    path: str
    text: str
    # Nanoseconds, so a save in the same second still counts as a change.
    modified: int


def editable_files(root: Path) -> dict[str, list[str]]:
    def listed(folder: str, suffixes: tuple[str, ...]) -> list[str]:
        found = sorted(p for p in (root / folder).glob("*") if p.suffix in suffixes)
        return [p.relative_to(root).as_posix() for p in found]

    return {
        "Settings": [defaults.CONFIG_FILENAME],
        "Instruments": listed(defaults.INSTRUMENTS_DIR, defaults.YAML_SUFFIXES),
        "Drafts": listed(defaults.DRAFTS_DIR, defaults.YAML_SUFFIXES),
        "Studies": listed(defaults.STUDIES_DIR, defaults.YAML_SUFFIXES),
        "Column maps": listed(defaults.MAPS_DIR, (".csv",)),
        "References": bib_file(root),
    }


def bib_file(root: Path) -> list[str]:
    # Only one inside the project, as the editor opens files by their path in it.
    try:
        path = bib_path(load_config(root), root).resolve()
    except MetadataError:
        return []
    if path.is_file() and path.is_relative_to(root.resolve()):
        return [path.relative_to(root.resolve()).as_posix()]
    return []


def custom_fields(root: Path) -> list[CustomFieldDef]:
    # The page still edits a project whose settings do not load, without these columns.
    try:
        return load_config(root).custom_fields
    except MetadataError:
        return []


def open_file(root: Path, relative: str) -> Opened:
    path = root / relative
    # Editors show one kind of line ending; saving puts the file's own back.
    text = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    return Opened(relative, text, path.stat().st_mtime_ns)


def check_text(relative: str, text: str) -> list[Issue]:
    # The same checks as loading the project, run on a copy so the file stays as it was.
    issues: list[Issue] = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if path.suffix == ".csv":
            load_variable_map(path, root, issues)
        elif path.suffix == ".bib":
            load_bibliography(path, root, issues)
        else:
            load_model(path, FOLDERS.get(path.parent.name, ProjectConfig), root, issues)
    return issues


def save_file(root: Path, opened: Opened, text: str) -> Opened:
    path = root / opened.path
    if path.stat().st_mtime_ns != opened.modified:
        raise EditError(
            f"{opened.path} changed on disk after you opened it; reload it to see the change"
        )
    newline = "\r\n" if b"\r\n" in path.read_bytes() else "\n"
    # The editor drops the last line break; every file ends with one.
    body = text.replace("\r\n", "\n").rstrip("\n") + "\n"
    path.write_bytes(body.replace("\n", newline).encode("utf-8"))
    return Opened(opened.path, text, path.stat().st_mtime_ns)


def save_freed(root: Path, freed: list[FreedParameter]) -> None:
    opened = open_file(root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    stats = data.setdefault("stats", CommentedMap())
    entries = CommentedSeq()
    for f in freed:
        entry = CommentedMap(f.model_dump())
        entry.fa.set_flow_style()
        entries.append(entry)
    if entries:
        stats["invariance_free"] = entries
    else:
        stats.pop("invariance_free", None)
    save_data(root, opened, data)


def save_step(root: Path, step: PrepareStep) -> None:
    # Takes the place of a step with the same name, or runs last.
    opened = open_file(root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    steps = data.setdefault("prepare", CommentedSeq())
    entry = CommentedMap(step.model_dump(exclude_none=True))
    entry.fa.set_flow_style()
    for key in ("inputs", "outputs"):
        entry[key] = CommentedSeq(entry[key])
        entry[key].fa.set_flow_style()
    at = next((n for n, s in enumerate(steps) if s.get("name") == step.name), None)
    if at is None:
        steps.append(entry)
    else:
        steps[at] = entry
    save_data(root, opened, data)


def save_analysis(root: Path, analysis: SavedAnalysis, script: str) -> None:
    # Takes the place of an analysis with the same name, or comes last.
    path = root / analysis.script
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    opened = open_file(root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    saved = data.setdefault("analyses", CommentedSeq())
    entry = CommentedMap(analysis.model_dump(exclude_defaults=True))
    for key in ("datasets", "variables"):
        if key in entry:
            entry[key] = CommentedSeq(entry[key])
            entry[key].fa.set_flow_style()
    at = next((n for n, s in enumerate(saved) if s.get("name") == analysis.name), None)
    if at is None:
        saved.append(entry)
    else:
        saved[at] = entry
    save_data(root, opened, data)


def remove_analysis(root: Path, analysis: SavedAnalysis) -> None:
    opened = open_file(root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    saved = data["analyses"]
    saved[:] = [s for s in saved if s.get("name") != analysis.name]
    if not saved:
        data.pop("analyses")
    save_data(root, opened, data)
    (root / analysis.script).unlink(missing_ok=True)


def save_settings(root: Path, changes: dict[str, dict[str, Any]]) -> None:
    # A setting equal to its default leaves the file, so the file holds only the lab's choices.
    opened = open_file(root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    for section, values in changes.items():
        default = ProjectConfig.model_fields[section].default_factory()
        held = data.setdefault(section, CommentedMap())
        for key, value in values.items():
            if value == getattr(default, key):
                held.pop(key, None)
            else:
                held[key] = value
        if not held:
            data.pop(section)
    save_data(root, opened, data)


def save_data(root: Path, opened: Opened, data: CommentedMap) -> None:
    out = io.StringIO()
    records.round_trip().dump(data, out)
    save_file(root, opened, out.getvalue())


def is_instrument_file(relative: str) -> bool:
    path = PurePosixPath(relative)
    return path.suffix in defaults.YAML_SUFFIXES and FOLDERS.get(path.parent.name) is Instrument


def instrument_from_text(text: str) -> Instrument:
    # For a preview while the file is being edited, so only the first problem is told.
    try:
        return Instrument.model_validate(yaml.safe_load(text))
    except yaml.YAMLError as err:
        raise EditError(f"Not valid YAML yet: {str(err).splitlines()[0]}") from None
    except ValidationError as err:
        first = err.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise EditError(f"{where}: {first['msg']}" if where else first["msg"]) from None


def new_tags(root: Path, text: str) -> dict[str, list[str]]:
    # Tags and choices typed into a file that their field's declaration does not list yet.
    fields = {
        f.name: f
        for f in custom_fields(root)
        if f.type in ("tags", "choice") and f.choices and not f.vocabulary
    }
    data = records.load(text)
    if not isinstance(data, dict):
        return {}
    blocks = [data.get("custom")]
    for key in ("scores", "items", "administrations", "datasets"):
        blocks += [entry.get("custom") for entry in data.get(key) or [] if isinstance(entry, dict)]
    blocks += [s.get("custom") for s in (data.get("studies") or {}).values() if isinstance(s, dict)]
    found: dict[str, list[str]] = {}
    for block in blocks:
        for name, value in (block or {}).items():
            if name not in fields:
                continue
            for tag in [value] if isinstance(value, str) else value or []:
                if tag not in fields[name].choices and tag not in found.get(name, []):
                    found.setdefault(name, []).append(str(tag))
    return found


def declare_tags(config_text: str, tags: dict[str, list[str]]) -> str:
    data = records.load(config_text)
    for field in data.get("custom_fields") or []:
        if field.get("name") in tags:
            field["choices"].extend(tags[field["name"]])
    out = io.StringIO()
    records.round_trip().dump(data, out)
    return out.getvalue()


def save_tags(root: Path, tags: dict[str, list[str]]) -> None:
    opened = open_file(root, defaults.CONFIG_FILENAME)
    save_file(root, opened, declare_tags(opened.text, tags))


def free_instrument_path(root: Path, instrument_id: str) -> Path:
    if not NEW_ID.fullmatch(instrument_id):
        raise EditError("Use lower-case letters, digits and underscores, starting with a letter")
    path = root / defaults.INSTRUMENTS_DIR / f"{instrument_id}.yaml"
    if path.exists():
        raise EditError(f"{path.relative_to(root).as_posix()} already exists")
    return path


def is_draft(relative: str) -> bool:
    return Path(relative).parent.name == defaults.DRAFTS_DIR


def move_draft(root: Path, relative: str) -> str:
    path = free_instrument_path(root, Path(relative).stem)
    path.parent.mkdir(exist_ok=True)
    (root / relative).rename(path)
    return path.relative_to(root).as_posix()


def new_instrument(root: Path, instrument_id: str) -> str:
    path = free_instrument_path(root, instrument_id)
    lines = [
        MODELINE.format("instrument"),
        f"id: {instrument_id}",
        f"name: {instrument_id.replace('_', ' ').capitalize()}",
        "response_sets: []",
        "items: []",
        "scores: []",
    ]
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.relative_to(root).as_posix()
