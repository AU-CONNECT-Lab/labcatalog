from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog import invariance
from labcatalog.ai_scoring import write_scoring_scripts
from labcatalog.cfa import CfaFit, build_models, fit_models
from labcatalog.check import CheckReport, check_project
from labcatalog.codegen import label_snippets, scoring_snippets
from labcatalog.exceptions import MetadataError
from labcatalog.invariance import InvarianceTest
from labcatalog.issues import Issue, has_errors
from labcatalog.llm import CallMetadata, make_llm_client
from labcatalog.manifest import Manifest, build_manifest
from labcatalog.prepare import Session, StepRun, run_steps
from labcatalog.project import Project, load_project, write_schemas
from labcatalog.resolve import Catalog, resolve_catalog
from labcatalog.scoring import compute_scores
from labcatalog.sources import LoadedDataset, load_datasets
from labcatalog.stats import Summary, summarize
from labcatalog.validate import validate_project


@dataclass
class CatalogResult:
    # Only the report is filled in when the metadata has errors.
    report: CheckReport
    project: Project | None = None
    catalog: Catalog | None = None
    summary: Summary | None = None
    snippets: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)
    label_snippets: dict[str, dict[str, str]] = field(default_factory=dict)
    manifest: Manifest | None = None
    # Row-level data stays for the charts that plot people rather than summaries.
    datasets: dict[str, LoadedDataset] = field(default_factory=dict)
    scores: dict[str, pd.DataFrame] = field(default_factory=dict)


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
        label_snippets=label_snippets(project.config, catalog),
        manifest=build_manifest(project, datasets),
        datasets=datasets,
        scores=scores,
    )


def load_validated(root: Path) -> tuple[Project | None, list[Issue]]:
    try:
        project = load_project(root)
    except MetadataError as err:
        return None, err.issues
    issues = validate_project(project)
    return (None if has_errors(issues) else project), issues


def run_cfa(result: CatalogResult, rscript: str) -> list[CfaFit]:
    models = build_models(result.project, result.catalog, result.datasets)
    return fit_models(models, rscript)


def run_invariance(result: CatalogResult, rscript: str) -> list[InvarianceTest]:
    models = invariance.build_models(result.project, result.catalog, result.datasets)
    return invariance.fit_models(models, rscript)


def run_scoring_script(
    result: CatalogResult, instrument_id: str, dataset: str, provider: str, model: str, url: str
) -> CallMetadata:
    client = make_llm_client(provider, model, url)
    return write_scoring_scripts(result.project, result.catalog, instrument_id, dataset, client)


def run_prepare(root: Path, echo: Callable[[str], None]) -> list[StepRun]:
    project = load_project(root)
    names = [step.name for step in project.config.prepare]
    return run_steps(project, names, Session(), echo=echo)


def run_schema(out_dir: Path) -> list[Path]:
    return write_schemas(out_dir)
