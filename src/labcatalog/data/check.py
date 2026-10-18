import re
from typing import Any

import pandas as pd
from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.config import missing_labels_for
from labcatalog.data import id_map
from labcatalog.data.ids import load_exclusions
from labcatalog.data.prepare import step_states
from labcatalog.data.resolve import Catalog, ResolvedVariable, numbers_in_range
from labcatalog.data.scoring import raw_items, scorable
from labcatalog.datalad.annex import fetch_advice
from labcatalog.datalad.check import check_git_annex
from labcatalog.issues import Issue, IssueLevel, has_errors
from labcatalog.paths import expand_path, portable_path
from labcatalog.project import Project
from labcatalog.sources import LoadedDataset, load_roster, load_roster_dataset

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


class CheckReport(BaseModel):
    issues: list[Issue] = []
    # Warnings someone looked at and recorded as fine; they are not in issues.
    accepted: list[Issue] = []

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
            *check_waves(project, datasets),
            *check_values(project, catalog, datasets),
            *id_map.check(project.root, {d.name for d in project.config.datasets}),
            *check_ids(project, datasets),
            *check_roster(project, datasets),
            *check_roster_columns(project, catalog),
            *check_exclusions(project, datasets),
            *check_identifier_columns(project, datasets),
            *check_dates(project, datasets),
            *check_same_answers(project, catalog, datasets),
            *check_score_agreement(project, catalog, datasets, scores),
            *check_prepare_outputs(project),
            *check_git_annex(project),
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
                where = f"{map_file}:{entry.line}"
                issues.append(
                    problem(
                        "column_missing",
                        message,
                        where,
                        dataset=name,
                        column=entry.column,
                        line=entry.line,
                    )
                )
        described = {entry.column for entry in entries}
        undescribed = [column for column in loaded.frame if column not in described]
        if undescribed:
            message = f"{len(undescribed)} column(s) not in {map_file}: {examples(undescribed)}"
            issues.append(
                problem(
                    "column_unmapped",
                    message,
                    location(project, loaded),
                    "warning",
                    dataset=name,
                    columns=undescribed,
                )
            )
    return issues


def check_waves(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    # A file holding several waves may have rows for a wave no dataset takes.
    files: dict[tuple, list[LoadedDataset]] = {}
    for loaded in datasets.values():
        if loaded.file_waves is not None:
            files.setdefault((loaded.source_path, loaded.config.wave_column), []).append(loaded)
    issues = []
    for (_, column), readers in files.items():
        left = readers[0].file_waves - {loaded.config.wave_in_file() for loaded in readers}
        if left:
            waves = examples(sorted(repr(wave) if not wave.strip() else wave for wave in left))
            message = f"{column} has rows for wave(s) that no dataset reads: {waves}"
            where = location(project, readers[0])
            # The last reader is what a dataset for a missing wave would repeat.
            issues.append(
                problem(
                    "wave_unclaimed",
                    message,
                    where,
                    "warning",
                    column=column,
                    dataset=readers[-1].config.name,
                    waves=sorted(wave for wave in left if wave.strip()),
                )
            )
    return issues


def check_values(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[Issue]:
    issues = []
    for variable in catalog.variables:
        loaded = datasets[variable.dataset]
        if variable.type == "text" or variable.column not in loaded.frame:
            continue
        codes = list(missing_labels_for(project.config, loaded.config))
        allowed = [option.value for option in variable.response_options] + codes
        values = loaded.frame[variable.column]
        numbers = loaded.numbers(variable.column)
        numeric_allowed = [float(v) for v in allowed if not isinstance(v, str)]
        numeric_allowed += [float(v) for v in codes if is_number(v)]
        ok = values.isin([str(v) for v in allowed]) | numbers.isin(numeric_allowed)
        if variable.type == "number":
            ok |= numbers_in_range(numbers, variable)
            expected = f"numbers{range_text(variable)}"
        else:
            expected = "response options"
        if not ok.all():
            stray = values[~ok]
            message = (
                f"{variable.column}: {len(stray)} value(s) are neither {expected} "
                f"nor missing codes: {examples(stray.unique())}"
            )
            issues.append(
                problem(
                    "unexpected_value",
                    message,
                    location(project, loaded),
                    dataset=variable.dataset,
                    column=variable.column,
                    instrument=variable.instrument_id,
                    item=variable.item_id,
                    values=[str(v) for v in stray.unique()],
                    rows=rows_of(~ok),
                )
            )
    return issues


def check_ids(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    issues = []
    for loaded in datasets.values():
        where = location(project, loaded)
        ids = loaded.frame[loaded.id_column]
        dataset_name = loaded.config.name
        clean, found = id_problems(project, ids, where, dataset=dataset_name)
        issues += found
        # With a roster, people missing from it are reported by check_roster instead.
        if loaded.group is not None and project.config.roster is None:
            no_group = clean & loaded.group.isna()
            if no_group.any():
                name = project.config.ids.group.name if project.config.ids.group else "group"
                message = f"{no_group.sum()} ID(s) give no {name} ID: {examples(ids[no_group])}"
                issues.append(
                    problem(
                        "group_missing",
                        message,
                        where,
                        "warning",
                        dataset=dataset_name,
                        rows=rows_of(no_group),
                    )
                )
    return issues


def id_problems(
    project: Project, ids: pd.Series, where: str, **details: Any
) -> tuple[pd.Series, list[Issue]]:
    pattern = project.config.ids.pattern
    issues = []
    blank = ids.str.strip() == ""
    spaced = ~blank & (ids != ids.str.strip())
    # Rows already reported for spaces are not reported again below.
    clean = ~blank & ~spaced
    if blank.any():
        message = f"{blank.sum()} row(s) have no ID"
        issues.append(problem("id_missing", message, where, rows=rows_of(blank), **details))
    if spaced.any():
        shown = examples([repr(value) for value in ids[spaced]])
        message = f"{spaced.sum()} ID(s) have leading or trailing spaces: {shown}"
        issues.append(problem("id_whitespace", message, where, rows=rows_of(spaced), **details))
    if pattern:
        mismatched = clean & ~ids.str.fullmatch(pattern)
        if mismatched.any():
            message = (
                f"{mismatched.sum()} ID(s) do not match ids.pattern: {examples(ids[mismatched])}"
            )
            issues.append(
                problem("id_pattern", message, where, rows=rows_of(mismatched), **details)
            )
    duplicated = clean & ids.duplicated(keep=False)
    if duplicated.any():
        repeated = ids[duplicated].unique()
        message = f"{len(repeated)} ID(s) appear more than once: {examples(repeated)}"
        issues.append(problem("id_duplicate", message, where, rows=rows_of(duplicated), **details))
    return clean, issues


def check_roster_columns(project: Project, catalog: Catalog) -> list[Issue]:
    # The roster's other columns are held to their instrument like a dataset's.
    roster = load_roster_dataset(project)
    if roster is None:
        return []
    found = {defaults.ROSTER: roster}
    described = Catalog(variables=catalog.roster_variables, scores=[])
    return [*check_columns(project, found), *check_values(project, described, found)]


def check_roster(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    roster = load_roster(project)
    if roster is None:
        return []
    where = portable_path(roster.path, project.root).as_posix()
    ids = roster.frame[roster.id_column]
    clean, issues = id_problems(project, ids, where)
    if roster.group_column:
        no_group = clean & (roster.frame[roster.group_column].str.strip() == "")
        if no_group.any():
            name = project.config.ids.group.name if project.config.ids.group else "group"
            message = f"{no_group.sum()} person(s) have no {name} ID: {examples(ids[no_group])}"
            issues.append(
                problem("group_missing", message, where, "warning", rows=rows_of(no_group))
            )
    listed = set(ids[clean])
    seen = set()
    for loaded in datasets.values():
        unlisted = pd.Series(False, index=loaded.frame.index)
        names: list[str] = []
        for column in filter(None, (loaded.id_column, loaded.config.respondent_column)):
            found = loaded.frame[column]
            seen.update(found.str.strip())
            # Blank and spaced IDs are reported by check_ids already.
            missing = (found.str.strip() == found) & (found != "") & ~found.isin(listed)
            unlisted |= missing
            names += list(dict.fromkeys(found[missing]))
        if unlisted.any():
            message = f"{len(names)} ID(s) are not in the roster: {examples(names)}"
            issues.append(
                problem(
                    "id_not_in_roster",
                    message,
                    location(project, loaded),
                    "warning",
                    dataset=loaded.config.name,
                    rows=rows_of(unlisted),
                )
            )
    unused = sorted(listed - seen)
    if unused:
        message = f"{len(unused)} person(s) in the roster are in no dataset: {examples(unused)}"
        issues.append(problem("roster_unused", message, where, "info"))
    return issues


def check_exclusions(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    if not project.config.exclusions:
        return []
    excluded = load_exclusions(expand_path(project.config.exclusions, project.root))
    issues = []
    for loaded in datasets.values():
        ids = loaded.frame[loaded.id_column]
        hits = ids.isin(excluded)
        if loaded.group is not None:
            hits |= loaded.group.isin(excluded)
        if hits.any():
            message = (
                f"{hits.sum()} row(s) belong to people or groups on the exclusion list: "
                f"{examples(ids[hits])}"
            )
            issues.append(
                problem(
                    "excluded_present",
                    message,
                    location(project, loaded),
                    dataset=loaded.config.name,
                    rows=rows_of(hits),
                )
            )
    return issues


def check_identifier_columns(project: Project, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    name_patterns = [re.compile(p, re.IGNORECASE) for p in defaults.IDENTIFIER_NAME_PATTERNS]
    free_text = {
        (instrument.id, item.id)
        for instrument in project.instruments.values()
        for item in instrument.items
        if item.type == "text"
    }
    issues = []
    for name, loaded in datasets.items():
        # Choice and number columns are already held to their allowed values by check_values.
        items = {
            e.column
            for e in project.maps.get(name, [])
            if e.instrument is not None and (e.instrument, e.item) not in free_text
        }
        for column in loaded.frame:
            if column == loaded.id_column:
                continue
            values = loaded.frame[column]
            reasons = []
            if any(p.search(column) for p in name_patterns):
                reasons.append("its name")
            if column in items:
                pass
            elif values.str.contains(EMAIL).any():
                reasons.append("values that look like email addresses")
            elif values.str.contains(PHONE).any():
                reasons.append("values that look like phone numbers")
            if reasons:
                message = f"{column} may hold identifying information ({' and '.join(reasons)})"
                issues.append(
                    problem(
                        "possible_identifier",
                        message,
                        location(project, loaded),
                        "warning",
                        dataset=name,
                        column=column,
                    )
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
            issues.append(
                problem(
                    "date_unparseable",
                    message,
                    location(project, loaded),
                    "warning",
                    dataset=loaded.config.name,
                    column=column,
                    rows=rows_of(bad),
                )
            )
    return issues


def check_same_answers(
    project: Project, catalog: Catalog, datasets: dict[str, LoadedDataset]
) -> list[Issue]:
    issues = []
    for score in catalog.scores:
        loaded = datasets[score.dataset]
        # On short scales the same answer to every item is common and says little.
        if len(score.columns) < defaults.SAME_ANSWER_MIN_ITEMS or not scorable(loaded, score):
            continue
        raw = raw_items(loaded, score)
        same = raw.notna().all(axis=1) & (raw.max(axis=1) == raw.min(axis=1))
        if same.any():
            message = (
                f"{score.key}: {same.sum()} participant(s) gave the same answer to every item: "
                f"{examples(loaded.frame.loc[same, loaded.id_column])}"
            )
            issues.append(
                problem(
                    "same_answer",
                    message,
                    location(project, loaded),
                    "warning",
                    dataset=score.dataset,
                    rows=rows_of(same),
                )
            )
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
        existing = loaded.numbers(column).where(~raw.isin(codes))
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


def range_text(variable: ResolvedVariable) -> str:
    low, high = variable.allowed_min, variable.allowed_max
    if low is not None and high is not None:
        return f" from {low:g} to {high:g}"
    if low is not None:
        return f" of at least {low:g}"
    if high is not None:
        return f" of at most {high:g}"
    return ""


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


def check_prepare_outputs(project: Project) -> list[Issue]:
    issues = []
    for state in step_states(project):
        where = f"prepare step {state.step.name}"
        for output in state.outputs:
            if output.modified is None:
                missing = (
                    fetch_advice(output.resolved)
                    if output.placeholder
                    else f"{output.path} does not exist; run the step"
                )
                issues.append(
                    problem(
                        "prepare_output_missing",
                        f"{where}: {missing}",
                        defaults.CONFIG_FILENAME,
                        "warning",
                        step=state.step.name,
                    )
                )
        if state.status == "outdated":
            newest = max(state.inputs, key=lambda f: f.modified)
            oldest = min(state.outputs, key=lambda f: f.modified)
            message = f"{where}: {oldest.path} is older than {newest.path}; run the step again"
            issues.append(
                problem(
                    "prepare_outdated",
                    message,
                    defaults.CONFIG_FILENAME,
                    "warning",
                    step=state.step.name,
                )
            )
    return issues


def rows_of(mask: pd.Series) -> list[int]:
    # Positions in the data file, counting from 0 below the header.
    return [int(n) for n in mask[mask].index]


def problem(
    code: str, message: str, where: str, level: IssueLevel = "error", **details: Any
) -> Issue:
    return Issue(level=level, code=code, message=message, location=where, details=details)
