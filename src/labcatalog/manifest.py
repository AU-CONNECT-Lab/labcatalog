import hashlib
import subprocess
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.annex import DATALAD_CONFIG, dataset_root
from labcatalog.paths import portable_path
from labcatalog.prepare import step_states
from labcatalog.project import Project
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
    changed = run_git(root, "status", "--porcelain", "--", *paths)
    return f"{head}-modified" if changed else head


def original_branch(root: Path) -> str:
    # git-annex on Windows works on adjusted/main(unlocked), a local branch that is never pushed.
    branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.startswith(ADJUSTED):
        return branch[len(ADJUSTED) : branch.index("(")]
    return "HEAD"


def datalad_records(project_root: Path, used: list[Path]) -> list[DataladRecord]:
    found: dict[Path, list[str]] = {}
    for path in used:
        if folder := dataset_root(path):
            relative = (path.parent.resolve() / path.name).relative_to(folder)
            found.setdefault(folder, []).append(relative.as_posix())
    records = (datalad_record(project_root, folder, paths) for folder, paths in found.items())
    return [record for record in records if record]


def datalad_record(project_root: Path, folder: Path, paths: list[str]) -> DataladRecord | None:
    try:
        branch = original_branch(folder)
        return DataladRecord(
            path=portable_path(folder, project_root.resolve()).as_posix(),
            id=run_git(folder, "config", "--file", DATALAD_CONFIG.as_posix(), "datalad.dataset.id"),
            # Only the files labcatalog used decide whether the dataset counts as modified.
            commit=commit_of(folder, branch, paths),
            tags=run_git(folder, "tag", "--points-at", branch).split(),
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
    sources = [d.source_path for d in datasets.values() if d.source_path is not None]
    inputs = [f.resolved for state in states for f in state.inputs]
    used = [project.root / defaults.CONFIG_FILENAME, *sources, *inputs]
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
        datalad=datalad_records(project.root, used),
    )
