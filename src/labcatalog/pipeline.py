from pathlib import Path

from pydantic import BaseModel

from labcatalog.check import CheckReport
from labcatalog.issues import Issue
from labcatalog.manifest import Manifest


class BuildResult(BaseModel):
    out_dir: Path
    issues: list[Issue]
    manifest: Manifest


def run_validate(root: Path) -> list[Issue]:
    raise NotImplementedError


def run_check(root: Path) -> CheckReport:
    raise NotImplementedError


def run_build(root: Path, out_dir: Path | None = None) -> BuildResult:
    raise NotImplementedError


def run_schema(out_dir: Path) -> list[Path]:
    raise NotImplementedError
