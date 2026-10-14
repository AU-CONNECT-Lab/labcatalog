from dataclasses import dataclass, field
from pathlib import Path

from labcatalog.check import CheckReport, check_project
from labcatalog.codegen import scoring_snippets
from labcatalog.exceptions import MetadataError
from labcatalog.issues import Issue, has_errors
from labcatalog.manifest import Manifest, build_manifest
from labcatalog.project import Project, load_project
from labcatalog.resolve import Catalog, resolve_catalog
from labcatalog.scoring import compute_scores
from labcatalog.sources import load_datasets
from labcatalog.stats import Summary, summarize
from labcatalog.validate import validate_project


@dataclass
class CatalogResult:
    # Only the report is filled in when the metadata has errors.
    report: CheckReport
    project: Project | None = None
    catalog: Catalog | None = None
    summary: Summary | None = None
    snippets: dict[str, dict[str, str]] = field(default_factory=dict)
    manifest: Manifest | None = None


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


def run_catalog(root: Path) -> CatalogResult:
    project, issues = load_validated(root)
    if project is None:
        return CatalogResult(report=CheckReport(issues=issues))
    catalog = resolve_catalog(project)
    datasets = load_datasets(project)
    scores = compute_scores(catalog, datasets)
    report = check_project(project, catalog, datasets, scores)
    return CatalogResult(
        report=CheckReport(issues=[*issues, *report.issues]),
        project=project,
        catalog=catalog,
        summary=summarize(catalog, datasets, scores, project.config),
        snippets=scoring_snippets(catalog),
        manifest=build_manifest(project, datasets),
    )


def load_validated(root: Path) -> tuple[Project | None, list[Issue]]:
    try:
        project = load_project(root)
    except MetadataError as err:
        return None, err.issues
    issues = validate_project(project)
    return (None if has_errors(issues) else project), issues


def run_schema(out_dir: Path) -> list[Path]:
    raise NotImplementedError
