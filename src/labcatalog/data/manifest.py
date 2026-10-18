import hashlib
import subprocess
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.config import ProjectConfig
from labcatalog.data.prepare import step_states
from labcatalog.datalad.annex import is_placeholder
from labcatalog.datalad.versions import (
    DataladRecord,
    commit_of,
    datalad_records,
    original_branch,
)
from labcatalog.paths import expand_path, portable_path
from labcatalog.project import Project, bib_path, references_root
from labcatalog.sources import LoadedDataset, load_roster
from labcatalog.version import __version__

CHUNK = 1 << 20


class FileRecord(BaseModel):
    dataset: str
    path: str
    sha256: str
    rows: int
    snapshot_date: date | None = None


class InputRecord(BaseModel):
    step: str
    path: str
    sha256: str


class Manifest(BaseModel):
    built_at: datetime
    tool_version: str
    metadata_commit: str | None = None
    files: list[FileRecord]
    # What the prepare steps read, so a number can be traced back to the raw files and scripts.
    inputs: list[InputRecord] = []
    datalad: list[DataladRecord] = []


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def folder_sha256(folder: Path) -> str:
    # Which files are there and how big, without reading what may be gigabytes of images.
    digest = hashlib.sha256()
    for path in sorted(p for p in folder.rglob("*") if not p.is_dir()):
        digest.update(f"{path.relative_to(folder).as_posix()}\t{path.lstat().st_size}\n".encode())
    return digest.hexdigest()


def git_commit(root: Path) -> str | None:
    # Metadata outside git, or a machine without git, simply has no commit to record.
    try:
        return commit_of(root, original_branch(root), ["."])
    except (OSError, subprocess.CalledProcessError):
        return None


def metadata_paths(root: Path) -> list[Path]:
    names = (
        defaults.CONFIG_FILENAME,
        defaults.INSTRUMENTS_DIR,
        defaults.STUDIES_DIR,
        defaults.MAPS_DIR,
        defaults.SCORING_DIR,
    )
    return present([root / name for name in names])


def used_paths(config: ProjectConfig, root: Path) -> list[Path]:
    metadata = [*metadata_paths(root), bib_path(config, root)]
    if config.references.root:
        metadata.append(references_root(config, root))
    if config.exclusions:
        metadata.append(expand_path(config.exclusions, root))
    if config.roster:
        metadata.append(expand_path(config.roster.path, root))
    sources = [expand_path(d.path, root) for d in config.datasets if d.path]
    inputs = [expand_path(path, root) for step in config.prepare for path in step.inputs]
    return present(list(dict.fromkeys([*metadata, *sources, *inputs])))


def present(paths: list[Path]) -> list[Path]:
    return [p for p in paths if p.exists() or is_placeholder(p)]


def roster_records(project: Project) -> list[FileRecord]:
    roster = load_roster(project)
    if roster is None:
        return []
    path = portable_path(roster.path, project.root).as_posix()
    return [
        FileRecord(
            dataset=defaults.ROSTER, path=path, sha256=file_sha256(roster.path), rows=len(roster.frame)
        )
    ]


def build_manifest(project: Project, datasets: dict[str, LoadedDataset]) -> Manifest:
    states = step_states(project)
    return Manifest(
        built_at=datetime.now().replace(microsecond=0),
        tool_version=__version__,
        metadata_commit=git_commit(project.root),
        files=[
            FileRecord(
                dataset=name,
                path=portable_path(loaded.source_path, project.root).as_posix(),
                sha256=folder_sha256(loaded.source_path)
                if loaded.source_path.is_dir()
                else file_sha256(loaded.source_path),
                rows=len(loaded.frame),
                snapshot_date=loaded.config.snapshot_date,
            )
            for name, loaded in datasets.items()
            if loaded.source_path is not None
        ]
        + roster_records(project),
        inputs=[
            InputRecord(step=state.step.name, path=f.path, sha256=file_sha256(f.resolved))
            for state in states
            for f in state.inputs
            if f.resolved.is_file() and not f.placeholder
        ],
        datalad=datalad_records(project.root, used_paths(project.config, project.root)),
    )
