import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.codebook import MODELINE
from labcatalog.config import ProjectConfig
from labcatalog.exceptions import EditError
from labcatalog.issues import Issue
from labcatalog.project import load_model
from labcatalog.schema import Instrument, StudyContent
from labcatalog.varmap import load_variable_map

FOLDERS: dict[str, type[BaseModel]] = {
    defaults.INSTRUMENTS_DIR: Instrument,
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
        "Studies": listed(defaults.STUDIES_DIR, defaults.YAML_SUFFIXES),
        "Column maps": listed(defaults.MAPS_DIR, (".csv",)),
    }


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


def new_instrument(root: Path, instrument_id: str) -> str:
    if not NEW_ID.fullmatch(instrument_id):
        raise EditError("Use lower-case letters, digits and underscores, starting with a letter")
    path = root / defaults.INSTRUMENTS_DIR / f"{instrument_id}.yaml"
    if path.exists():
        raise EditError(f"{path.relative_to(root).as_posix()} already exists")
    lines = [
        MODELINE.format("instrument"),
        f"id: {instrument_id}",
        f"name: {instrument_id.replace('_', ' ').capitalize()}",
        "items: []",
        "scores: []",
    ]
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path.relative_to(root).as_posix()
