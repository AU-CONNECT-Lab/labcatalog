from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog.project import Project
from labcatalog.sources import LoadedDataset


class FileRecord(BaseModel):
    dataset: str
    path: str
    sha256: str
    rows: int
    snapshot_date: date | None = None


class Manifest(BaseModel):
    built_at: datetime
    tool_version: str
    metadata_commit: str | None = None
    files: list[FileRecord]


def file_sha256(path: Path) -> str:
    raise NotImplementedError


def git_commit(root: Path) -> str | None:
    raise NotImplementedError


def build_manifest(project: Project, datasets: dict[str, LoadedDataset]) -> Manifest:
    raise NotImplementedError
