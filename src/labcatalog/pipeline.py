import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog import defaults
from labcatalog.ai.cleaning import CleaningDraft, draft_script, fix_script
from labcatalog.ai.custom import AnalysisDraft, draft_analysis, fix_analysis
from labcatalog.ai.instrument import InstrumentDraft, draft_instrument
from labcatalog.ai.interpret import Interpretation, interpret
from labcatalog.ai.measures import Draft, draft_description
from labcatalog.ai.scoring import write_scoring_scripts
from labcatalog.ai.search import Search, search_catalog
from labcatalog.data.check import CheckReport, check_project
from labcatalog.data.manifest import Manifest, build_manifest, metadata_paths, used_paths
from labcatalog.data.prepare import prepare_lock
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
from labcatalog.datalad.history import Saved, history, rerun
from labcatalog.datalad.sync import (
    DatasetState,
    branch_name,
    clone,
    dataset_states,
    drop_all,
    get_all,
    project_datasets,
    push_datasets,
    save_datasets,
    update_datasets,
)
from labcatalog.exceptions import FreezeError, MetadataError, ProjectNotFoundError
from labcatalog.issues import Issue, has_errors
from labcatalog.llm import CallMetadata, make_llm_client
from labcatalog.metadata import accepted
from labcatalog.metadata.validate import validate_project
from labcatalog.paths import expand_path
from labcatalog.project import Project, load_config, load_project, references_root, write_schemas
from labcatalog.reports.codegen import label_snippets, scoring_snippets
from labcatalog.reports.tables import PaperTable
from labcatalog.sources import LoadedDataset, load_datasets, load_roster_datasets
from labcatalog.stats import invariance
from labcatalog.stats.cfa import CfaFit, build_models, fit_models
from labcatalog.stats.invariance import InvarianceTest
from labcatalog.stats.summary import Summary, summarize, summarize_variable


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
    # Each study's roster whose columns an instrument describes.
    rosters: dict[str, LoadedDataset] = field(default_factory=dict)
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
    rosters = load_roster_datasets(project)
    summary = summarize(catalog, datasets, scores, project.config)
    summary.roster = [
        summarize_variable(rosters[v.study], v, project.config)
        for v in catalog.roster_variables
        if v.study in rosters and v.column in rosters[v.study].frame
    ]
    return CatalogResult(
        report=reported(root, [*issues, *report.issues]),
        project=project,
        catalog=catalog,
        summary=summary,
        snippets=scoring_snippets(catalog),
        label_snippets=label_snippets(project.config, catalog),
        manifest=build_manifest(project, datasets),
        datasets=datasets,
        scores=scores,
        rosters=rosters,
    )


def load_validated(root: Path) -> tuple[Project | None, list[Issue]]:
    try:
        project = load_project(root)
    except MetadataError as err:
        return None, err.issues
    issues = validate_project(project)
    return (None if has_errors(issues) else project), issues


def run_cfa(result: CatalogResult, rscript: str | None, estimator: str) -> list[CfaFit]:
    models = build_models(result.project, result.catalog, result.datasets)
    return fit_models(models, rscript, estimator)


def run_invariance(result: CatalogResult, rscript: str, estimator: str) -> list[InvarianceTest]:
    models = invariance.build_models(result.project, result.catalog, result.datasets)
    return invariance.fit_models(models, rscript, estimator)


def run_scoring_script(
    result: CatalogResult, instrument_id: str, dataset: str, provider: str, model: str, url: str
) -> CallMetadata:
    client = make_llm_client(provider, model, url)
    return write_scoring_scripts(result.project, result.catalog, instrument_id, dataset, client)


def run_cleaning_draft(
    result: CatalogResult,
    dataset: str,
    raw: str,
    language: str,
    provider: str,
    model: str,
    url: str,
) -> CleaningDraft:
    client = make_llm_client(provider, model, url)
    return draft_script(result.project, result.catalog, dataset, raw, language, client)


def run_cleaning_fix(
    result: CatalogResult,
    issue: Issue,
    rows: list[dict[str, str]],
    provider: str,
    model: str,
    url: str,
) -> CleaningDraft:
    client = make_llm_client(provider, model, url)
    return fix_script(result.project, result.catalog, issue, rows, client)


def run_analysis_draft(
    columns: str,
    wanted: str,
    language: str,
    data_file: str,
    start: str,
    provider: str,
    model: str,
    url: str,
) -> AnalysisDraft:
    client = make_llm_client(provider, model, url)
    return draft_analysis(columns, wanted, language, data_file, client, start)


def run_analysis_fix(
    columns: str,
    wanted: str,
    language: str,
    data_file: str,
    script: str,
    ran: str,
    provider: str,
    model: str,
    url: str,
) -> AnalysisDraft:
    client = make_llm_client(provider, model, url)
    return fix_analysis(columns, wanted, language, data_file, script, ran, client)


def run_description_draft(
    result: CatalogResult, instrument_id: str, provider: str, model: str, url: str
) -> Draft:
    client = make_llm_client(provider, model, url)
    return draft_description(result.project, instrument_id, client)


def run_instrument_draft(
    root: Path,
    instrument_id: str,
    pdf: Path,
    provider: str,
    model: str,
    url: str,
    which: str = "",
) -> InstrumentDraft:
    client = make_llm_client(provider, model, url)
    return draft_instrument(root, instrument_id, pdf, client, which)


def run_search(result: CatalogResult, query: str, provider: str, model: str, url: str) -> Search:
    client = make_llm_client(provider, model, url)
    return search_catalog(result.project, query, client)


def run_interpretation(
    shown: list[PaperTable], paragraph: str, provider: str, model: str, url: str
) -> Interpretation:
    client = make_llm_client(provider, model, url)
    return interpret(shown, paragraph, client)


def run_freeze(root: Path, name: str, datalad: str | None) -> tuple[Path, Freeze]:
    # Reloads first, so the freeze is of the files as they are now.
    result = run_catalog(root)
    if result.project is None:
        raise MetadataError(result.report.issues)
    participants = {d.dataset: d.n_ids for d in result.summary.datasets}
    # Here, since the database module builds on this one.
    from labcatalog.reports.database import write_database

    return freeze_project(
        result.project,
        result.datasets,
        participants,
        name,
        datalad,
        lambda path: write_database(result, path),
    )


def run_push_freeze(root: Path, name: str, datalad: str) -> list[Path]:
    return push_freeze(freeze_roots(load_project(root)), name, datalad)


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


def data_datasets(root: Path) -> list[Path]:
    root = root.resolve()
    return project_datasets(load_config(root), root)


def run_data_status(root: Path) -> list[DatasetState]:
    return dataset_states(data_datasets(root))


def run_data_save(root: Path, message: str, datalad: str, author: str | None = None) -> list[Path]:
    return save_datasets(data_datasets(root), message, datalad, author)


def run_data_update(root: Path, datalad: str) -> list[Path]:
    # New versions bring files this clone has no content for yet.
    updated = update_datasets(data_datasets(root), datalad)
    run_get_missing(root, datalad)
    return updated


def run_data_push(root: Path, datalad: str) -> list[Path]:
    return push_datasets(data_datasets(root), datalad)


def run_history(dataset: Path) -> list[Saved]:
    return history(dataset, branch_name(dataset))


def run_rerun(root: Path, dataset: Path, commit: str, datalad: str) -> None:
    # A rerun writes what the prepare steps write, so it waits for anyone running them.
    with prepare_lock(root):
        rerun(dataset, commit, datalad)


def run_get_dataset(dataset: Path, datalad: str) -> None:
    get_all(dataset, datalad)


def run_drop_dataset(dataset: Path, datalad: str) -> None:
    drop_all(dataset, datalad)


def run_clone(url: str, folder: Path, datalad: str) -> Path:
    root = clone(url, folder, datalad)
    if not (root / defaults.CONFIG_FILENAME).is_file():
        raise ProjectNotFoundError(
            f"Cloned into {root}, but it has no {defaults.CONFIG_FILENAME}, so it is not a "
            "labcatalog project"
        )
    run_get_missing(root, datalad)
    return root


def run_open_freeze(root: Path, name: str, datalad: str, folder: Path | None = None) -> Path:
    freezes = list_freezes(root)
    record = next((f for f in freezes if f.name == name), None)
    if record is None:
        known = ", ".join(f.name for f in freezes) or "none yet"
        raise FreezeError(f"No freeze named {name}; the freezes are: {known}")
    folder = folder or Path(tempfile.mkdtemp(prefix=f"labcatalog-{name}-"))
    copy = open_freeze(root.resolve(), record, folder, datalad)
    run_get_missing(copy, datalad)
    return copy


def run_schema(out_dir: Path) -> list[Path]:
    return write_schemas(out_dir)
