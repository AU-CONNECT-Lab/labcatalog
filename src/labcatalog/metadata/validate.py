import re
from collections import Counter
from datetime import date
from typing import Any

from labcatalog import defaults
from labcatalog.config import CustomFieldDef, missing_codes_for
from labcatalog.issues import Issue, IssueLevel
from labcatalog.metadata.varmap import MapEntry
from labcatalog.project import Project, bib_path, reference_pdf, references_root
from labcatalog.reports import measures, participants
from labcatalog.schema import Administration, Instrument

CONFIG = defaults.CONFIG_FILENAME


def validate_project(project: Project) -> list[Issue]:
    return [
        *check_vocab(project),
        *check_cross_references(project),
        *check_custom_fields(project),
        *check_browse(project),
        *check_missing_code_collisions(project),
        *check_variable_maps(project),
        *check_data_settings(project),
        *check_references(project),
        *check_prepare_steps(project),
        *check_templates(project),
    ]


def check_vocab(project: Project) -> list[Issue]:
    config = project.config
    vocab = config.vocab
    issues = [
        not_in_vocab(f"vocab.modality_labels.{modality}", modality, "vocab.modalities")
        for modality in vocab.modality_labels
        if modality not in vocab.modalities
    ]
    for n, dataset in enumerate(config.datasets, start=1):
        where = f"datasets[{n}] ({dataset.name})"
        if dataset.modality not in vocab.modalities:
            issues.append(
                not_in_vocab(
                    f"{where}.modality",
                    dataset.modality,
                    "vocab.modalities",
                    dataset=dataset.name,
                    field="modality",
                )
            )
        if dataset.reporter not in vocab.reporters:
            issues.append(
                not_in_vocab(
                    f"{where}.reporter",
                    dataset.reporter,
                    "vocab.reporters",
                    dataset=dataset.name,
                    field="reporter",
                )
            )
        study = config.studies.get(dataset.study)
        if study is None:
            issues.append(
                unknown(
                    f"{where}.study: '{dataset.study}' is not under studies",
                    CONFIG,
                    path=["datasets", n - 1, "study"],
                    value=dataset.study,
                    choices=list(config.studies),
                )
            )
        elif dataset.wave not in study.waves:
            message = f"{where}.wave: wave {dataset.wave} is not listed for study {dataset.study}"
            issues.append(unknown(message, CONFIG))
    for name, content in project.studies.items():
        found = [
            not_in_vocab(f"methods.{modality}", modality, "vocab.modalities")
            for modality in content.methods
            if modality not in vocab.modalities
        ]
        for n, administration in enumerate(content.administrations, start=1):
            target = administration.target
            if target and target not in vocab.targets:
                found.append(
                    not_in_vocab(
                        f"administrations[{n}].target",
                        target,
                        "vocab.targets",
                        study=name,
                        administration=n - 1,
                        field="target",
                    )
                )
        for issue in found:
            issue.location = project.study_files[name]
        issues.extend(found)
    return issues


def check_cross_references(project: Project) -> list[Issue]:
    config = project.config
    datasets = {dataset.name: dataset for dataset in config.datasets}
    issues = [
        problem("duplicate_id", f"dataset name '{name}' is used more than once", CONFIG)
        for name, count in Counter(d.name for d in config.datasets).items()
        if count > 1
    ]
    for name, content in project.studies.items():
        location = project.study_files[name]
        if content.study not in config.studies:
            message = f"study: '{content.study}' is not under studies in {CONFIG}"
            issues.append(unknown(message, location))
        for n, administration in enumerate(content.administrations, start=1):
            where = f"administrations[{n}]"
            instrument = project.instruments.get(administration.instrument)
            if instrument is None:
                message = f"{where}.instrument: no instrument with id '{administration.instrument}'"
                issues.append(
                    unknown(
                        message,
                        location,
                        path=["administrations", n - 1, "instrument"],
                        value=administration.instrument,
                        choices=sorted(project.instruments),
                    )
                )
                continue
            for k, dataset_name in enumerate(administration.datasets):
                dataset = datasets.get(dataset_name)
                if dataset is None:
                    message = f"{where}.datasets: no dataset named '{dataset_name}' in {CONFIG}"
                    issues.append(
                        unknown(
                            message,
                            location,
                            path=["administrations", n - 1, "datasets", k],
                            value=dataset_name,
                            choices=[d.name for d in datasets.values() if d.study == content.study],
                        )
                    )
                elif dataset.study != content.study:
                    message = f"{where}.datasets: '{dataset_name}' belongs to study {dataset.study}"
                    issues.append(unknown(message, location))
            item_ids = {item.id for item in instrument.items}
            set_ids = {response_set.id for response_set in instrument.response_sets}
            for m, override in enumerate(administration.overrides, start=1):
                prefix = f"{where}.overrides[{m}]"
                if override.item not in item_ids:
                    message = f"{prefix}.item: {instrument.id} has no item '{override.item}'"
                    issues.append(
                        unknown(
                            message,
                            location,
                            path=["administrations", n - 1, "overrides", m - 1, "item"],
                            value=override.item,
                            choices=sorted(item_ids),
                        )
                    )
                if override.dataset and override.dataset not in administration.datasets:
                    message = (
                        f"{prefix}.dataset: '{override.dataset}' is not in this administration"
                    )
                    issues.append(unknown(message, location))
                if override.response_set and override.response_set not in set_ids:
                    message = f"{prefix}.response_set: no response set '{override.response_set}'"
                    issues.append(unknown(message, location))
    for instrument_id, instrument in project.instruments.items():
        issues.extend(check_instrument(instrument, project.instrument_files[instrument_id]))
    return issues


def check_instrument(instrument: Instrument, location: str) -> list[Issue]:
    issues = []
    for label, ids in [
        ("item", [item.id for item in instrument.items]),
        ("response set", [response_set.id for response_set in instrument.response_sets]),
        ("score", [score.id for score in instrument.scores]),
    ]:
        for value, count in Counter(ids).items():
            if count > 1:
                issues.append(
                    problem("duplicate_id", f"{label} id '{value}' is used {count} times", location)
                )
    set_ids = {response_set.id for response_set in instrument.response_sets}
    for n, response_set in enumerate(instrument.response_sets, start=1):
        values = Counter(str(option.value) for option in response_set.options)
        for value, count in values.items():
            if count > 1:
                message = (
                    f"response_sets[{n}] ({response_set.id}): value {value} is listed {count} times"
                )
                issues.append(problem("duplicate_id", message, location))
    if instrument.default_response_set and instrument.default_response_set not in set_ids:
        message = f"default_response_set: no response set '{instrument.default_response_set}'"
        issues.append(
            unknown(
                message,
                location,
                path=["default_response_set"],
                value=instrument.default_response_set,
                choices=sorted(set_ids),
            )
        )
    for n, item in enumerate(instrument.items, start=1):
        where = f"items[{n}] ({item.id})"
        if item.response_set and item.response_set not in set_ids:
            message = f"{where}.response_set: no response set '{item.response_set}'"
            issues.append(
                unknown(
                    message,
                    location,
                    path=["items", n - 1, "response_set"],
                    value=item.response_set,
                    choices=sorted(set_ids),
                )
            )
        if item.type != "choice" and item.response_set:
            message = f"{where}.response_set: {item.type} items have no response options"
            issues.append(problem("invalid_value", message, location))
        if item.type == "choice" and not (item.response_set or instrument.default_response_set):
            message = f"{where}: needs a response_set, or type: number or text"
            issues.append(problem("invalid_value", message, location))
        if item.type != "number" and (item.min is not None or item.max is not None):
            message = f"{where}: min and max apply to number items only"
            issues.append(problem("invalid_value", message, location))
        if item.min is not None and item.max is not None and item.min > item.max:
            issues.append(problem("invalid_value", f"{where}: min is above max", location))
    items = {item.id: item for item in instrument.items}
    sets = {response_set.id: response_set for response_set in instrument.response_sets}
    for n, score in enumerate(instrument.scores, start=1):
        where = f"scores[{n}] ({score.id})"
        absent = [item_id for item_id in score.items if item_id not in items]
        if absent:
            issues.append(unknown(f"{where}.items: no item(s) {', '.join(absent)}", location))
        unscorable = []
        for item_id in score.items:
            if item_id not in items:
                continue
            if items[item_id].type != "choice":
                message = (
                    f"{where}.items: {item_id} is a {items[item_id].type} item and cannot be scored"
                )
                issues.append(problem("invalid_value", message, location))
                continue
            response_set = sets.get(items[item_id].response_set or instrument.default_response_set)
            numeric = response_set is not None and all(
                isinstance(option.value, int | float) for option in response_set.options
            )
            if not numeric:
                unscorable.append(item_id)
        if unscorable:
            message = f"{where}.items: need numeric response options: {', '.join(unscorable)}"
            issues.append(problem("invalid_value", message, location))
        if score.min_valid is not None and not 1 <= score.min_valid <= len(score.items):
            message = f"{where}.min_valid: must be between 1 and {len(score.items)}"
            issues.append(problem("invalid_value", message, location))
        if score.min_valid is not None and score.missing_rule == "complete":
            message = f"{where}.min_valid: has no effect while missing_rule is complete"
            issues.append(problem("invalid_value", message, location, level="warning"))
        if instrument.kind == "demographics" and score.missing_rule != "complete":
            message = f"{where}.missing_rule: demographic answers are never imputed; use complete"
            issues.append(problem("invalid_value", message, location))
    return issues


def check_custom_fields(project: Project) -> list[Issue]:
    config = project.config
    fields = {field.name: field for field in config.custom_fields}
    issues = []
    for field in config.custom_fields:
        if field.type == "choice" and not field.choices:
            message = f"custom_fields ({field.name}): a choice field needs choices"
            issues.append(problem("invalid_value", message, CONFIG))

    def check(owner: str, values: dict[str, Any], where: str, location: str) -> None:
        for key, value in values.items():
            field = fields.get(key)
            if field is None:
                message = f"{where}custom.{key}: not declared under custom_fields in {CONFIG}"
                issues.append(problem("undeclared_custom_field", message, location))
            elif field.applies_to != owner:
                message = f"{where}custom.{key}: declared for {field.applies_to}, not {owner}"
                issues.append(problem("undeclared_custom_field", message, location))
            elif reason := custom_value_problem(field, value):
                issues.append(problem("invalid_value", f"{where}custom.{key}: {reason}", location))

    for instrument_id, instrument in project.instruments.items():
        location = project.instrument_files[instrument_id]
        check("instrument", instrument.custom, "", location)
        for n, score in enumerate(instrument.scores, start=1):
            check("score", score.custom, f"scores[{n}] ({score.id}).", location)
    for name, content in project.studies.items():
        for n, administration in enumerate(content.administrations, start=1):
            where = f"administrations[{n}]."
            check("administration", administration.custom, where, project.study_files[name])
    for n, dataset in enumerate(config.datasets, start=1):
        check("dataset", dataset.custom, f"datasets[{n}] ({dataset.name}).", CONFIG)
    return issues


def check_browse(project: Project) -> list[Issue]:
    config = project.config
    fields = {field.name: field for field in config.custom_fields}
    builtin = ", ".join(defaults.BUILTIN_FACETS)
    issues = [
        problem(
            "invalid_value",
            f"custom_fields ({name}): the name is taken by a built-in facet ({builtin})",
            CONFIG,
        )
        for name in fields
        if name in defaults.BUILTIN_FACETS
    ]
    facets = config.browse.facets or []
    for name, count in Counter(facets).items():
        if count > 1:
            issues.append(
                problem("duplicate_id", f"browse.facets: '{name}' is listed twice", CONFIG)
            )
    for name in dict.fromkeys(facets):
        if name in defaults.BUILTIN_FACETS:
            continue
        field = fields.get(name)
        if field is None:
            message = f"browse.facets: '{name}' is neither a built-in facet ({builtin}) nor a custom field"
            issues.append(unknown(message, CONFIG))
        elif field.type not in defaults.FACET_FIELD_TYPES:
            message = f"browse.facets: '{name}' is a {field.type} field; only choice and tags fields can be facets"
            issues.append(problem("invalid_value", message, CONFIG))
    return issues


def custom_value_problem(field: CustomFieldDef, value: Any) -> str | None:
    if field.type == "text":
        return None if isinstance(value, str) else "expected text"
    if field.type == "number":
        is_number = isinstance(value, int | float) and not isinstance(value, bool)
        return None if is_number else "expected a number"
    if field.type == "date":
        return None if isinstance(value, date) else "expected a date such as 2026-01-31"
    if field.type == "choice":
        allowed = field.choices or []
        return None if str(value) in allowed else f"'{value}' is not one of {', '.join(allowed)}"
    if not isinstance(value, list) or not all(isinstance(tag, str) for tag in value):
        return "expected a list of tags"
    undeclared = [tag for tag in value if field.choices is not None and tag not in field.choices]
    return f"tag(s) not declared: {', '.join(undeclared)}" if undeclared else None


def check_missing_code_collisions(project: Project) -> list[Issue]:
    config = project.config
    datasets = {dataset.name: dataset for dataset in config.datasets}
    messages: dict[str, str] = {}
    for content in project.studies.values():
        for administration in content.administrations:
            instrument = project.instruments.get(administration.instrument)
            if instrument is None:
                continue
            for dataset_name in administration.datasets:
                dataset = datasets.get(dataset_name)
                if dataset is None:
                    continue
                codes = {str(m.code): m.label for m in missing_codes_for(config, dataset)}
                for response_set in instrument.response_sets:
                    for option in response_set.options:
                        label = codes.get(str(option.value))
                        if label is not None:
                            message = (
                                f"response set '{response_set.id}' uses {option.value}, which is "
                                f"also the missing code '{label}' (dataset {dataset_name})"
                            )
                            where = (project.instrument_files[instrument.id], dataset_name, option)
                            messages.setdefault(message, where)
    return [
        problem("missing_code_collision", m, loc, dataset=name, value=str(option.value))
        for m, (loc, name, option) in messages.items()
    ]


def check_variable_maps(project: Project) -> list[Issue]:
    config = project.config
    administered: dict[str, dict[str, Administration]] = {}
    for content in project.studies.values():
        for administration in content.administrations:
            for dataset_name in administration.datasets:
                administered.setdefault(dataset_name, {})[administration.instrument] = (
                    administration
                )
    dataset_names = {dataset.name for dataset in config.datasets}
    issues = [
        unknown(f"no dataset named '{name}' in {CONFIG}", f"{defaults.MAPS_DIR}/{name}.csv")
        for name in project.maps
        if name not in dataset_names
    ]
    for dataset in config.datasets:
        expected = administered.get(dataset.name, {})
        entries = project.maps.get(dataset.name)
        location = f"{defaults.MAPS_DIR}/{dataset.name}.csv"
        if entries is None:
            if expected:
                message = f"dataset {dataset.name} has administrations but no {location}"
                issues.append(problem("map_missing", message, CONFIG))
            continue
        seen_columns: dict[str, int] = {}
        seen_items: dict[tuple[str, str], MapEntry] = {}
        stray_rows: dict[str, list[int]] = {}
        for entry in entries:
            where = f"{location}:{entry.line}"
            if entry.column in seen_columns:
                message = (
                    f"column {entry.column} is already listed on line {seen_columns[entry.column]}"
                )
                lines = [seen_columns[entry.column], entry.line]
                issues.append(
                    problem("duplicate_id", message, where, dataset=dataset.name, lines=lines)
                )
                continue
            seen_columns[entry.column] = entry.line
            if entry.instrument is None:
                continue
            if entry.instrument not in expected:
                stray_rows.setdefault(entry.instrument, []).append(entry.line)
                continue
            instrument = project.instruments[entry.instrument]
            if entry.score_id is not None:
                if entry.score_id not in {score.id for score in instrument.scores}:
                    issues.append(
                        unknown(f"{instrument.id} has no score '{entry.score_id}'", where)
                    )
                    continue
            elif entry.item not in {item.id for item in instrument.items}:
                issues.append(unknown(f"{instrument.id} has no item '{entry.item}'", where))
                continue
            key = (entry.instrument, entry.item)
            if key in seen_items:
                first = seen_items[key]
                message = f"{entry.instrument} {entry.item} is already mapped to {first.column}"
                lines = [first.line, entry.line]
                issues.append(
                    problem("duplicate_id", message, where, dataset=dataset.name, lines=lines)
                )
            seen_items[key] = entry
        # One issue per instrument, so a single typo upstream does not flood the list.
        for name, lines in stray_rows.items():
            message = (
                f"instrument '{name}' is not administered in {dataset.name} ({len(lines)} rows)"
            )
            issues.append(unknown(message, f"{location}:{lines[0]}"))
        for instrument_id, administration in expected.items():
            instrument = project.instruments.get(instrument_id)
            if instrument is None:
                continue
            dropped = {
                override.item
                for override in administration.overrides
                if override.dropped and override.dataset in (None, dataset.name)
            }
            mapped = {item for (inst, item) in seen_items if inst == instrument_id}
            unmapped = [
                item.id
                for item in instrument.items
                if item.id not in mapped and item.id not in dropped
            ]
            if unmapped:
                shown = ", ".join(unmapped[:5]) + (" ..." if len(unmapped) > 5 else "")
                message = f"{instrument_id}: {len(unmapped)} item(s) have no column: {shown}"
                issues.append(
                    problem(
                        "unmapped_item",
                        message,
                        location,
                        level="warning",
                        dataset=dataset.name,
                        instrument=instrument_id,
                        items=unmapped,
                    )
                )
    return issues


def check_data_settings(project: Project) -> list[Issue]:
    config = project.config
    issues = []
    group = config.ids.group
    for name, pattern in [
        ("pattern", config.ids.pattern),
        ("group.from_id", group.from_id if group else None),
    ]:
        if pattern is None:
            continue
        try:
            groups = re.compile(pattern).groups
        except re.error as err:
            issues.append(problem("invalid_value", f"ids.{name}: invalid pattern: {err}", CONFIG))
            continue
        if name == "group.from_id" and groups != 1:
            message = "ids.group.from_id: needs exactly one (...) around the group part of the ID"
            issues.append(problem("invalid_value", message, CONFIG))
    for n, dataset in enumerate(config.datasets, start=1):
        where = f"datasets[{n}] ({dataset.name})"
        if dataset.source == "csv" and not dataset.path:
            issues.append(problem("invalid_value", f"{where}: a csv dataset needs a path", CONFIG))
        if dataset.source == "folder" and not (dataset.path and dataset.files):
            message = f"{where}: a folder dataset needs a path (the folder) and files"
            issues.append(problem("invalid_value", message, CONFIG))
        elif dataset.files is not None and dataset.files.count("{id}") != 1:
            message = f"{where}.files: needs {{id}} once, where each file's path holds the ID"
            issues.append(problem("invalid_value", message, CONFIG))
        if dataset.source != "folder" and dataset.files is not None:
            message = f"{where}.files: only folder datasets take files"
            issues.append(problem("invalid_value", message, CONFIG))
        if dataset.group_column and group is None:
            message = f"{where}.group_column: declare ids.group (its name) first"
            issues.append(problem("invalid_value", message, CONFIG))
        if group and not group.from_id and not dataset.group_column:
            message = f"{where}: needs group_column, or ids.group.from_id for every dataset"
            issues.append(problem("invalid_value", message, CONFIG))
    allowed = {"id", "none"} | ({group.name} if group else set())
    if config.stats.correlate_by not in allowed:
        message = f"stats.correlate_by: '{config.stats.correlate_by}' is not one of {', '.join(sorted(allowed))}"
        issues.append(problem("invalid_value", message, CONFIG))
    return issues


def check_references(project: Project) -> list[Issue]:
    # A shared folder not yet synced on this computer should not block the catalog.
    root = references_root(project.config, project.root)
    if not root.is_dir():
        message = f"references.root: folder not found: {root}"
        return [problem("references_root_missing", message, CONFIG, "warning")]
    issues = []
    keys = [
        (f"studies.{name}.reference", study.reference, CONFIG, ["studies", name, "reference"])
        for name, study in project.config.studies.items()
        if study.reference
    ] + [
        (
            f"references[{n}].key",
            reference.key,
            project.instrument_files[instrument_id],
            ["references", n - 1, "key"],
        )
        for instrument_id, instrument in project.instruments.items()
        for n, reference in enumerate(instrument.references, start=1)
    ]
    if not bib_path(project.config, project.root).is_file():
        if keys:
            message = f"references.root: no {defaults.BIB_FILENAME} in {root}"
            issues.append(problem("bib_missing", message, CONFIG, "warning"))
    else:
        choices = sorted(project.bibliography)
        for where, key, location, path in keys:
            if key not in project.bibliography:
                message = f"{where}: '{key}' is not in {defaults.BIB_FILENAME}"
                issues.append(
                    problem(
                        "reference_missing",
                        message,
                        location,
                        "warning",
                        path=path,
                        value=key,
                        choices=choices,
                    )
                )
    for instrument_id, instrument in project.instruments.items():
        for n, reference in enumerate(instrument.references, start=1):
            if not reference.pdf:
                continue
            path = reference_pdf(project, reference.pdf)
            if not path.is_file():
                message = f"references[{n}].pdf: file not found: {path}"
                location = project.instrument_files[instrument_id]
                issues.append(problem("pdf_missing", message, location, "warning"))
    return issues


def check_prepare_steps(project: Project) -> list[Issue]:
    steps = project.config.prepare
    issues = [
        problem("duplicate_id", f"prepare: step name '{name}' is used more than once", CONFIG)
        for name, count in Counter(step.name for step in steps).items()
        if count > 1
    ]
    for n, step in enumerate(steps, start=1):
        where = f"prepare[{n}] ({step.name})"
        if not step.run.strip():
            issues.append(problem("invalid_value", f"{where}.run: the command is empty", CONFIG))
        if not step.outputs:
            message = f"{where}.outputs: list at least one file the step writes"
            issues.append(problem("invalid_value", message, CONFIG))
    return issues


def check_templates(project: Project) -> list[Issue]:
    config = project.config
    templates = [
        ("measures", config.measures, CONFIG, measures.PLACEHOLDERS),
        ("participants", config.participants, CONFIG, participants.PLACEHOLDERS),
        *[
            ("measures", instrument.measures, project.instrument_files[name], measures.PLACEHOLDERS)
            for name, instrument in project.instruments.items()
        ],
        *[
            (
                "participants",
                content.participants,
                project.study_files[name],
                participants.PLACEHOLDERS,
            )
            for name, content in project.studies.items()
        ],
    ]
    return [
        problem("invalid_value", f"{where}: {found}", location)
        for where, template, location, allowed in templates
        if template and (found := measures.placeholder_problem(template, allowed))
    ]


def problem(
    code: str, message: str, location: str, level: IssueLevel = "error", **details: Any
) -> Issue:
    return Issue(level=level, code=code, message=message, location=location, details=details)


def unknown(message: str, location: str, **details: Any) -> Issue:
    # Where one value holds the wrong ID: its path in the file, the value and the IDs it could be.
    return problem("unknown_reference", message, location, **details)


def not_in_vocab(where: str, value: str, vocab: str, **details: Any) -> Issue:
    # The vocab list, the value and, where one entry holds it, which entry, for the Fix panel.
    kind = vocab.removeprefix("vocab.")
    message = f"{where}: '{value}' is not in {vocab}"
    return problem("not_in_vocab", message, CONFIG, vocab=kind, value=value, **details)
