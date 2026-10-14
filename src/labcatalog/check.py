import re

import pandas as pd
from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.config import missing_codes_for, missing_labels_for
from labcatalog.ids import load_exclusions
from labcatalog.issues import Issue, IssueLevel, has_errors
from labcatalog.paths import expand_path, portable_path
from labcatalog.project import Project
from labcatalog.resolve import Catalog
from labcatalog.sources import LoadedDataset

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


class CheckReport(BaseModel):
    issues: list[Issue] = []

    def has_errors(self) -> bool:
        return has_errors(self.issues)


def check_project(
    project: Project,
    catalog: Catalog,
    datasets: dict[str, LoadedDataset],
    scores: dict[str, pd.DataFrame],
) -> CheckReport:
    return CheckReport(
        issues=[
            *check_columns(project, datasets),
            *check_values(project, catalog, datasets),
            *check_ids(project, datasets),
            *check_exclusions(project, datasets),
            *check_identifier_columns(project, datasets),
            *check_dates(project, datasets),
            *check_score_agreement(project, catalog, datasets, scores),
        ]
    )


def check_columns(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    issues = []
    for name, loaded in datasets.items():
        entries = project.maps.get(name)
        if entries is None:
            continue
        map_file = f"{defaults.MAPS_DIR}/{name}.csv"
        for entry in entries:
            if entry.column not in loaded.frame:
                message = f"{entry.column} is listed in the map but not in the data"
                issues.append(problem("column_missing", message, f"{map_file}:{entry.line}"))
        described = {entry.column for entry in entries}
        undescribed = [column for column in loaded.frame if column not in described]
        if undescribed:
            message = f"{len(undescribed)} column(s) not in {map_file}: {examples(undescribed)}"
            issues.append(problem("column_unmapped", message, location(project, loaded), "warning"))
    return issues


def check_values(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[Issue]:
    issues = []
    for variable in catalog.variables:
        loaded = datasets[variable.dataset]
        if not variable.response_options or variable.column not in loaded.frame:
            continue
        codes = list(missing_labels_for(project.config, loaded.config))
        allowed = [option.value for option in variable.response_options] + codes
        values = loaded.frame[variable.column]
        numbers = pd.to_numeric(values, errors="coerce")
        numeric_allowed = [float(v) for v in allowed if not isinstance(v, str)]
        numeric_allowed += [float(v) for v in codes if is_number(v)]
        ok = values.isin([str(v) for v in allowed]) | numbers.isin(numeric_allowed)
        if not ok.all():
            stray = values[~ok]
            message = (
                f"{variable.column}: {len(stray)} value(s) are neither response options "
                f"nor missing codes: {examples(stray.unique())}"
            )
            issues.append(problem("unexpected_value", message, location(project, loaded)))
    return issues


def check_ids(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    pattern = project.config.ids.pattern
    issues = []
    for loaded in datasets.values():
        where = location(project, loaded)
        ids = loaded.frame[loaded.id_column]
        blank = ids.str.strip() == ""
        spaced = ~blank & (ids != ids.str.strip())
        # Rows already reported for spaces are not reported again below.
        clean = ~blank & ~spaced
        if blank.any():
            issues.append(problem("id_missing", f"{blank.sum()} row(s) have no ID", where))
        if spaced.any():
            shown = examples([repr(value) for value in ids[spaced]])
            message = f"{spaced.sum()} ID(s) have leading or trailing spaces: {shown}"
            issues.append(problem("id_whitespace", message, where))
        if pattern:
            mismatched = clean & ~ids.str.fullmatch(pattern)
            if mismatched.any():
                message = f"{mismatched.sum()} ID(s) do not match ids.pattern: {examples(ids[mismatched])}"
                issues.append(problem("id_pattern", message, where))
        duplicated = clean & ids.duplicated(keep=False)
        if duplicated.any():
            repeated = ids[duplicated].unique()
            message = f"{len(repeated)} ID(s) appear more than once: {examples(repeated)}"
            issues.append(problem("id_duplicate", message, where))
        if loaded.family is not None:
            no_family = clean & loaded.family.isna()
            if no_family.any():
                message = f"{no_family.sum()} ID(s) give no family ID: {examples(ids[no_family])}"
                issues.append(problem("family_missing", message, where, "warning"))
    return issues


def check_exclusions(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    if not project.config.exclusions:
        return []
    excluded = load_exclusions(expand_path(project.config.exclusions, project.root))
    issues = []
    for loaded in datasets.values():
        ids = loaded.frame[loaded.id_column]
        hits = ids.isin(excluded)
        if loaded.family is not None:
            hits |= loaded.family.isin(excluded)
        if hits.any():
            message = (
                f"{hits.sum()} row(s) belong to people or families on the exclusion list: "
                f"{examples(ids[hits])}"
            )
            issues.append(problem("excluded_present", message, location(project, loaded)))
    return issues


def check_identifier_columns(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    name_patterns = [re.compile(p, re.IGNORECASE) for p in defaults.IDENTIFIER_NAME_PATTERNS]
    issues = []
    for loaded in datasets.values():
        for column in loaded.frame:
            if column == loaded.id_column:
                continue
            values = loaded.frame[column]
            reasons = []
            if any(p.search(column) for p in name_patterns):
                reasons.append("its name")
            if values.str.contains(EMAIL).any():
                reasons.append("values that look like email addresses")
            elif values.str.contains(PHONE).any():
                reasons.append("values that look like phone numbers")
            if reasons:
                message = f"{column} may hold identifying information ({' and '.join(reasons)})"
                issues.append(
                    problem("possible_identifier", message, location(project, loaded), "warning")
                )
    return issues


def check_dates(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    issues = []
    for loaded in datasets.values():
        column = loaded.config.date_column
        if column is None or column not in loaded.frame:
            continue
        values = loaded.frame[column]
        parsed = pd.to_datetime(values, format=project.config.defaults.date_format, errors="coerce")
        bad = parsed.isna() & (values.str.strip() != "")
        if bad.any():
            message = (
                f"{column}: {bad.sum()} date(s) do not match {project.config.defaults.date_format}: "
                f"{examples(values[bad])}"
            )
            issues.append(problem("date_unparseable", message, location(project, loaded), "warning"))
    return issues


def check_score_agreement(
    project: Project,
    catalog: Catalog,
    datasets: dict[str, LoadedDataset],
    scores: dict[str, pd.DataFrame],
) -> list[Issue]:
    issues = []
    for score in catalog.scores:
        loaded = datasets[score.dataset]
        column = score.existing_column
        if column is None or column not in loaded.frame:
            continue
        raw = loaded.frame[column]
        codes = list(missing_labels_for(project.config, loaded.config))
        existing = pd.to_numeric(raw.where(~raw.isin(codes)), errors="coerce")
        # Compare at the precision the lab's own script wrote.
        places = raw.str.extract(r"\.(\d+)$", expand=False).str.len()
        decimals = int(places.max()) if places.notna().any() else 0
        computed = scores[score.dataset][score.key].round(decimals)
        both = existing.notna() & computed.notna()
        differ = both & (existing.round(decimals) != computed)
        one_sided = existing.notna() != computed.notna()
        where = location(project, loaded)
        if differ.any():
            message = (
                f"{score.key}: {differ.sum()} row(s) differ from {column}, "
                f"for example {examples(loaded.frame.loc[differ, loaded.id_column])}"
            )
            issues.append(problem("score_mismatch", message, where))
        if one_sided.any():
            message = (
                f"{score.key}: {one_sided.sum()} row(s) have a score on only one side ({column})"
            )
            issues.append(problem("score_coverage", message, where, "warning"))
    return issues


def is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def location(project: Project, loaded: LoadedDataset) -> str:
    if loaded.source_path is None:
        return loaded.config.name
    return portable_path(loaded.source_path, project.root).as_posix()


def examples(values) -> str:
    values = [str(value) for value in values]
    shown = ", ".join(values[: defaults.EXAMPLE_VALUES])
    return shown + (" ..." if len(values) > defaults.EXAMPLE_VALUES else "")


def problem(code: str, message: str, where: str, level: IssueLevel = "error") -> Issue:
    return Issue(level=level, code=code, message=message, location=where)
