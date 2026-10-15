import hashlib
import subprocess
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog.paths import portable_path
from labcatalog.prepare import step_states
from labcatalog.project import Project
from labcatalog.sources import LoadedDataset
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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(root: Path) -> str | None:
    # Metadata outside git, or a machine without git, simply has no commit to record.
    try:
        head = run_git(root, "rev-parse", "--short", "HEAD")
        changed = run_git(root, "status", "--porcelain", "--", ".")
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{head}-modified" if changed else head


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def build_manifest(project: Project, datasets: dict[str, LoadedDataset]) -> Manifest:
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
            for state in step_states(project)
            for f in state.inputs
            if f.resolved.is_file()
        ],
    )
