import hashlib
import subprocess
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.config import ProjectConfig, roster_name
from labcatalog.data.prepare import step_states
from labcatalog.datalad.annex import is_placeholder
from labcatalog.datalad.versions import (
    DataladRecord,
    commit_of,
    datalad_records,
    original_branch,
)
from labcatalog.exceptions import LabCatalogError
from labcatalog.paths import expand_path, portable_path
from labcatalog.project import Project, bib_path, load_config, references_root
from labcatalog.sources import LoadedDataset, load_rosters
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
    for study in config.studies.values():
        if study.exclusions:
            metadata.append(expand_path(study.exclusions, root))
        if study.roster:
            metadata.append(expand_path(study.roster.path, root))
    sources = [expand_path(p, root) for d in config.datasets for p in (d.path, *d.scores) if p]
    inputs = [expand_path(path, root) for step in config.prepare for path in step.inputs]
    return present(list(dict.fromkeys([*metadata, *sources, *inputs])))


def file_times(root: Path) -> dict[Path, int]:
    # When each file the catalog reads last changed; folder datasets and PDFs would take too long.
    paths = [root / name for name in (defaults.ACCEPTED_FILENAME, defaults.ID_MAP_FILENAME)]
    for path in metadata_paths(root):
        paths += sorted(path.rglob("*")) if path.is_dir() else [path]
    try:
        config = load_config(root)
    except LabCatalogError:
        # Half-edited settings still let the files they do not name be watched.
        config = None
    if config is not None:
        paths.append(bib_path(config, root))
        for study in config.studies.values():
            roster = study.roster.path if study.roster else None
            paths += [expand_path(p, root) for p in (study.exclusions, roster) if p]
        paths += [
            expand_path(d.path, root) for d in config.datasets if d.source == "csv" and d.path
        ]
        paths += [expand_path(p, root) for d in config.datasets for p in d.scores]
    return {p: p.stat().st_mtime_ns for p in dict.fromkeys(paths) if p.is_file()}


def changed(before: dict[Path, int], after: dict[Path, int]) -> list[Path]:
    return sorted(p for p in before.keys() | after.keys() if before.get(p) != after.get(p))


def present(paths: list[Path]) -> list[Path]:
    return [p for p in paths if p.exists() or is_placeholder(p)]


def roster_records(project: Project) -> list[FileRecord]:
    return [
        FileRecord(
            dataset=roster_name(study),
            path=portable_path(roster.path, project.root).as_posix(),
            sha256=file_sha256(roster.path),
            rows=len(roster.frame),
        )
        for study, roster in load_rosters(project).items()
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
