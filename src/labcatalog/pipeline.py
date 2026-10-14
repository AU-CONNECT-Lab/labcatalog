from pathlib import Path

from pydantic import BaseModel

from labcatalog.check import CheckReport, check_project
from labcatalog.exceptions import MetadataError
from labcatalog.issues import Issue, has_errors
from labcatalog.manifest import Manifest
from labcatalog.project import Project, load_project
from labcatalog.resolve import resolve_catalog
from labcatalog.scoring import compute_scores
from labcatalog.sources import load_datasets
from labcatalog.validate import validate_project


class BuildResult(BaseModel):
    out_dir: Path
    issues: list[Issue]
    manifest: Manifest


def run_validate(root: Path) -> list[Issue]:
    return load_validated(root)[1]


def run_check(root: Path) -> CheckReport:
    project, issues = load_validated(root)
    if project is None:
        return CheckReport(issues=issues)
    catalog = resolve_catalog(project)
    datasets = load_datasets(project)
    report = check_project(project, catalog, datasets, compute_scores(catalog, datasets))
    return CheckReport(issues=[*issues, *report.issues])


def load_validated(root: Path) -> tuple[Project | None, list[Issue]]:
    try:
        project = load_project(root)
    except MetadataError as err:
        return None, err.issues
    issues = validate_project(project)
    return (None if has_errors(issues) else project), issues


def run_build(root: Path) -> BuildResult:
    raise NotImplementedError


def run_schema(out_dir: Path) -> list[Path]:
    raise NotImplementedError
