import hashlib
import subprocess
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.annex import DATALAD_CONFIG, group_by_dataset, is_placeholder
from labcatalog.paths import expand_path, portable_path
from labcatalog.prepare import step_states
from labcatalog.project import Project, bib_path, references_root
from labcatalog.sources import LoadedDataset
from labcatalog.version import __version__

CHUNK = 1 << 20
ADJUSTED = "adjusted/"


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


class DataladRecord(BaseModel):
    path: str
    id: str
    commit: str
    tags: list[str] = []


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


def git_commit(root: Path) -> str | None:
    # Metadata outside git, or a machine without git, simply has no commit to record.
    try:
        return commit_of(root, original_branch(root), ["."])
    except (OSError, subprocess.CalledProcessError):
        return None


def commit_of(root: Path, branch: str, paths: list[str]) -> str:
    head = run_git(root, "rev-parse", "--short", branch)
    changed = run_git(root, "status", "--porcelain", "--", *paths) or unsynced(root, branch)
    return f"{head}-modified" if changed else head


def unsynced(root: Path, branch: str) -> bool:
    # A synced adjusted branch is one git-annex commit on top of the original branch.
    return branch != "HEAD" and run_git(root, "rev-parse", "HEAD^") != run_git(
        root, "rev-parse", branch
    )


def tags_at(root: Path, branch: str) -> list[str]:
    # datalad save --version-tag tags the adjusted commit, a plain git tag the original one.
    found = {*run_git(root, "tag", "--points-at", "HEAD").split()}
    found.update(run_git(root, "tag", "--points-at", branch).split())
    return sorted(found)


def original_branch(root: Path) -> str:
    # git-annex on Windows works on adjusted/main(unlocked), a local branch that is never pushed.
    branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.startswith(ADJUSTED):
        return branch[len(ADJUSTED) : branch.index("(")]
    return "HEAD"


def used_paths(project: Project, datasets: dict[str, LoadedDataset]) -> list[Path]:
    config, root = project.config, project.root
    metadata = [
        root / name
        for name in (
            defaults.CONFIG_FILENAME,
            defaults.INSTRUMENTS_DIR,
            defaults.STUDIES_DIR,
            defaults.MAPS_DIR,
            defaults.SCORING_DIR,
        )
    ]
    metadata.append(bib_path(config, root))
    if config.references.root:
        metadata.append(references_root(config, root))
    if config.exclusions:
        metadata.append(expand_path(config.exclusions, root))
    sources = [d.source_path for d in datasets.values() if d.source_path is not None]
    inputs = [f.resolved for state in step_states(project) for f in state.inputs]
    found = dict.fromkeys(
        p for p in [*metadata, *sources, *inputs] if p.exists() or is_placeholder(p)
    )
    return list(found)


def datalad_records(project_root: Path, used: list[Path]) -> list[DataladRecord]:
    groups = group_by_dataset(used)
    records = (datalad_record(project_root, folder, paths) for folder, paths in groups.items())
    return [record for record in records if record]


def datalad_record(project_root: Path, folder: Path, paths: list[str]) -> DataladRecord | None:
    try:
        branch = original_branch(folder)
        return DataladRecord(
            path=portable_path(folder, project_root.resolve()).as_posix(),
            id=run_git(folder, "config", "--file", DATALAD_CONFIG.as_posix(), "datalad.dataset.id"),
            # Only the files labcatalog used decide whether the dataset counts as modified.
            commit=commit_of(folder, branch, paths),
            tags=tags_at(folder, branch),
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


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
                sha256=file_sha256(loaded.source_path),
                rows=len(loaded.frame),
                snapshot_date=loaded.config.snapshot_date,
            )
            for name, loaded in datasets.items()
            if loaded.source_path is not None
        ],
        inputs=[
            InputRecord(step=state.step.name, path=f.path, sha256=file_sha256(f.resolved))
            for state in states
            for f in state.inputs
            if f.resolved.is_file() and not f.placeholder
        ],
        datalad=datalad_records(project.root, used_paths(project, datasets)),
    )
