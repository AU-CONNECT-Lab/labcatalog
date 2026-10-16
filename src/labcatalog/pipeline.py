import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog.ai.instrument import InstrumentDraft, draft_instrument
from labcatalog.ai.measures import Draft, draft_description
from labcatalog.ai.scoring import write_scoring_scripts
from labcatalog.ai.search import Search, search_catalog
from labcatalog.codebook import core as codebook
from labcatalog.codebook.core import ImportResult
from labcatalog.data.check import CheckReport, check_project
from labcatalog.data.manifest import Manifest, build_manifest, metadata_paths, used_paths
from labcatalog.data.prepare import Session, StepRun, run_steps
from labcatalog.data.resolve import Catalog, resolve_catalog
from labcatalog.data.scoring import compute_scores
from labcatalog.datalad.bridge import get_content
from labcatalog.datalad.freeze import (
    Freeze,
    freeze_project,
    freeze_roots,
    list_freezes,
    open_freeze,
    push_freeze,
)
from labcatalog.exceptions import CodebookError, MetadataError
from labcatalog.issues import Issue, has_errors
from labcatalog.llm import CallMetadata, make_llm_client
from labcatalog.metadata import accepted
from labcatalog.metadata.validate import validate_project
from labcatalog.paths import expand_path
from labcatalog.project import Project, load_config, load_project, references_root, write_schemas
from labcatalog.reports.codegen import label_snippets, scoring_snippets
from labcatalog.sources import LoadedDataset, load_datasets
from labcatalog.stats import invariance
from labcatalog.stats.cfa import CfaFit, build_models, fit_models
from labcatalog.stats.invariance import InvarianceTest
from labcatalog.stats.summary import Summary, summarize


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
    return reported(root, load_validated(root)[1]).issues


def run_check(root: Path) -> CheckReport:
    project, issues = load_validated(root)
    if project is None:
        return reported(root, issues)
    catalog = resolve_catalog(project)
    datasets = load_datasets(project)
    report = check_project(project, catalog, datasets, compute_scores(catalog, datasets))
    return reported(root, [*issues, *report.issues])


def reported(root: Path, issues: list[Issue]) -> CheckReport:
    # Problems in the accepted-warnings file itself are reported like any other.
    entries = accepted.load(root.resolve(), issues)
    shown, hidden = accepted.split(issues, entries)
    return CheckReport(issues=shown, accepted=hidden)


def run_catalog(root: Path) -> CatalogResult:
    project, issues = load_validated(root)
    if project is None:
        return CatalogResult(report=reported(root, issues))
    catalog = resolve_catalog(project)
    datasets = load_datasets(project)
    scores = compute_scores(catalog, datasets)
    report = check_project(project, catalog, datasets, scores)
    return CatalogResult(
        report=reported(root, [*issues, *report.issues]),
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


def run_cfa(result: CatalogResult, rscript: str | None) -> list[CfaFit]:
    models = build_models(result.project, result.catalog, result.datasets)
    return fit_models(models, rscript, result.project.config.stats.cfa_estimator)


def run_invariance(result: CatalogResult, rscript: str) -> list[InvarianceTest]:
    models = invariance.build_models(result.project, result.catalog, result.datasets)
    return invariance.fit_models(models, rscript, result.project.config.stats.cfa_estimator)


def run_codebook_create(root: Path, dataset: str, dictionary: Path | None) -> list[Path]:
    project = load_project(root)
    codebook.require_unmapped(project, dataset)
    return codebook.write_templates(project, dataset, dictionary)


def run_codebook_prompt(root: Path, dataset: str) -> str:
    project = load_project(root)
    codebook.require_unmapped(project, dataset)
    if not codebook.codebook_paths(project, dataset)[codebook.ITEMS].is_file():
        raise CodebookError(
            f"Create the codebook files first: labcatalog codebook create {dataset}"
        )
    return codebook.ai_prompt(project, dataset)


def run_codebook_import(root: Path, dataset: str) -> ImportResult:
    project = load_project(root)
    codebook.require_unmapped(project, dataset)
    return codebook.import_codebook(project, dataset)


def run_scoring_script(
    result: CatalogResult, instrument_id: str, dataset: str, provider: str, model: str, url: str
) -> CallMetadata:
    client = make_llm_client(provider, model, url)
    return write_scoring_scripts(result.project, result.catalog, instrument_id, dataset, client)


def run_description_draft(
    result: CatalogResult, instrument_id: str, provider: str, model: str, url: str
) -> Draft:
    client = make_llm_client(provider, model, url)
    return draft_description(result.project, instrument_id, client)


def run_instrument_draft(
    root: Path, instrument_id: str, pdf: Path, provider: str, model: str, url: str
) -> InstrumentDraft:
    client = make_llm_client(provider, model, url)
    return draft_instrument(root, instrument_id, pdf, client)


def run_search(result: CatalogResult, query: str, provider: str, model: str, url: str) -> Search:
    client = make_llm_client(provider, model, url)
    return search_catalog(result.project, query, client)


def run_freeze(root: Path, name: str, datalad: str | None) -> tuple[Path, Freeze]:
    # Reloads first, so the freeze is of the files as they are now.
    result = run_catalog(root)
    if result.project is None:
        raise MetadataError(result.report.issues)
    participants = {d.dataset: d.n_ids for d in result.summary.datasets}
    return freeze_project(result.project, result.datasets, participants, name, datalad)


def run_push_freeze(root: Path, name: str, datalad: str) -> list[Path]:
    return push_freeze(freeze_roots(load_project(root)), name, datalad)


def run_prepare(root: Path, echo: Callable[[str], None], datalad: str | None) -> list[StepRun]:
    project = load_project(root)
    names = [step.name for step in project.config.prepare]
    return run_steps(project, names, Session(), echo=echo, datalad=datalad)


def run_get(paths: list[Path], datalad: str) -> None:
    get_content(datalad, paths)


def run_get_missing(root: Path, datalad: str) -> None:
    root = root.resolve()
    # The metadata first: until they are here the project cannot say which data it reads.
    get_content(datalad, metadata_paths(root))
    config = load_config(root)
    # Reference PDFs come one at a time, when someone opens them.
    pdfs = references_root(config, root) if config.references.root else None
    # Folder datasets read only paths, so their files stay where they are.
    folders = {
        expand_path(d.path, root) for d in config.datasets if d.source == "folder" and d.path
    }
    get_content(datalad, [p for p in used_paths(config, root) if p != pdfs and p not in folders])


def run_open_freeze(root: Path, name: str, datalad: str) -> Path:
    record = next(f for f in list_freezes(root) if f.name == name)
    folder = Path(tempfile.mkdtemp(prefix=f"labcatalog-{name}-"))
    copy = open_freeze(root.resolve(), record, folder, datalad)
    run_get_missing(copy, datalad)
    return copy


def run_schema(out_dir: Path) -> list[Path]:
    return write_schemas(out_dir)
