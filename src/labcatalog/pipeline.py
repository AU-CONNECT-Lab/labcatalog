from pathlib import Path

from pydantic import BaseModel

from labcatalog.check import CheckReport
from labcatalog.exceptions import MetadataError
from labcatalog.issues import Issue
from labcatalog.manifest import Manifest
from labcatalog.project import load_project


class BuildResult(BaseModel):
    out_dir: Path
    issues: list[Issue]
    manifest: Manifest


def run_validate(root: Path) -> list[Issue]:
    try:
        load_project(root)
    except MetadataError as err:
        return err.issues
    return []


def run_check(root: Path) -> CheckReport:
    raise NotImplementedError


def run_build(root: Path) -> BuildResult:
    raise NotImplementedError


def run_schema(out_dir: Path) -> list[Path]:
    raise NotImplementedError
