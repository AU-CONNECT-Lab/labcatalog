import pandas as pd
from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.config import DatasetConfig, roster_dataset
from labcatalog.project import Project
from labcatalog.schema import Administration, Instrument, ItemType, ResponseOption, Text

DEFAULT_TEXT_KEY = "default"


class ResolvedVariable(BaseModel):
    column: str
    instrument_id: str
    item_id: str
    dataset: str
    study: str
    wave: str
    reporter: str
    modality: str
    target: str | None = None
    label: str | None = None
    text: dict[str, str]
    type: ItemType = "choice"
    response_options: list[ResponseOption]
    # The response set the options come from, after overrides; None for numbers and text.
    response_set: str | None = None
    allowed_min: float | None = None
    allowed_max: float | None = None
    reverse: bool
    reversed_in_data: bool
    subscales: list[str] = []


def numbers_in_range(numbers: pd.Series, variable: ResolvedVariable) -> pd.Series:
    ok = numbers.notna()
    if variable.allowed_min is not None:
        ok &= numbers >= variable.allowed_min
    if variable.allowed_max is not None:
        ok &= numbers <= variable.allowed_max
    return ok


class ResolvedScore(BaseModel):
    key: str
    instrument_id: str
    score_id: str
    dataset: str
    label: str
    method: str
    columns: list[str]
    reverse_columns: list[str]
    reverse_bounds: dict[str, tuple[float, float]]
    valid_values: dict[str, list[float]]
    reversed_in_data: bool
    missing_rule: str
    min_valid: int | None = None
    existing_column: str | None = None
    unavailable_items: list[str] = []


class Catalog(BaseModel):
    variables: list[ResolvedVariable]
    scores: list[ResolvedScore]
    # The roster's described columns; not given in any dataset, so kept apart.
    roster_variables: list[ResolvedVariable] = []

    def variables_for(self, dataset: str) -> list[ResolvedVariable]:
        return [variable for variable in self.variables if variable.dataset == dataset]

    def scores_for(self, dataset: str) -> list[ResolvedScore]:
        return [score for score in self.scores if score.dataset == dataset]


def resolve_catalog(project: Project) -> Catalog:
    datasets = {dataset.name: dataset for dataset in project.config.datasets}
    variables, scores = [], []
    for content in project.studies.values():
        for administration in content.administrations:
            instrument = project.instruments[administration.instrument]
            for dataset_name in administration.datasets:
                dataset = datasets[dataset_name]
                columns = mapped_columns(project, dataset, instrument.id)
                resolved = resolve_items(instrument, administration, dataset, columns)
                variables.extend(resolved)
                scores.extend(
                    resolve_scores(instrument, administration, dataset, resolved, columns)
                )
    return Catalog(variables=variables, scores=scores, roster_variables=resolve_roster(project))


def resolve_roster(project: Project) -> list[ResolvedVariable]:
    roster = project.config.roster
    instrument = (
        project.instruments.get(roster.instrument) if roster and roster.instrument else None
    )
    if instrument is None:
        return []
    administration = Administration(instrument=instrument.id, datasets=[defaults.ROSTER])
    dataset = roster_dataset(project.config)
    columns = mapped_columns(project, dataset, instrument.id)
    return resolve_items(instrument, administration, dataset, columns)


def mapped_columns(project: Project, dataset: DatasetConfig, instrument_id: str) -> dict[str, str]:
    return {
        entry.item: entry.column
        for entry in project.maps.get(dataset.map_name(), [])
        if entry.instrument == instrument_id
    }


def resolve_items(
    instrument: Instrument,
    administration: Administration,
    dataset: DatasetConfig,
    columns: dict[str, str],
) -> list[ResolvedVariable]:
    response_sets = {response_set.id: response_set for response_set in instrument.response_sets}
    resolved = []
    for item in instrument.items:
        text, set_id, dropped = item.text, item.response_set, False
        # Later overrides win; an override without a dataset applies to every dataset.
        for override in administration.overrides:
            if override.item != item.id or override.dataset not in (None, dataset.name):
                continue
            text = override.text if override.text is not None else text
            set_id = override.response_set or set_id
            dropped = dropped or override.dropped
        column = columns.get(item.id)
        if dropped or column is None:
            continue
        set_id = set_id or instrument.default_response_set
        options = response_sets[set_id].options if set_id and item.type == "choice" else []
        resolved.append(
            ResolvedVariable(
                column=column,
                instrument_id=instrument.id,
                item_id=item.id,
                dataset=dataset.name,
                study=dataset.study,
                wave=dataset.wave,
                reporter=dataset.reporter,
                modality=dataset.modality,
                target=administration.target,
                label=item.label,
                text=as_text_dict(text),
                type=item.type,
                response_options=options,
                response_set=set_id if options else None,
                allowed_min=item.min,
                allowed_max=item.max,
                reverse=item.reverse,
                reversed_in_data=administration.reversed_in_data,
                subscales=item.subscales,
            )
        )
    return resolved


def resolve_scores(
    instrument: Instrument,
    administration: Administration,
    dataset: DatasetConfig,
    variables: list[ResolvedVariable],
    columns: dict[str, str],
) -> list[ResolvedScore]:
    by_item = {variable.item_id: variable for variable in variables}
    scores = []
    for score in instrument.scores:
        present = [by_item[item_id] for item_id in score.items if item_id in by_item]
        reversed_items = [variable for variable in present if variable.reverse]
        scores.append(
            ResolvedScore(
                key=f"{instrument.id}.{score.id}@{dataset.name}",
                instrument_id=instrument.id,
                score_id=score.id,
                dataset=dataset.name,
                label=score.label,
                method=score.method,
                columns=[variable.column for variable in present],
                reverse_columns=[variable.column for variable in reversed_items],
                reverse_bounds={
                    variable.column: option_bounds(variable.response_options)
                    for variable in reversed_items
                },
                valid_values={
                    variable.column: [float(option.value) for option in variable.response_options]
                    for variable in present
                },
                reversed_in_data=administration.reversed_in_data,
                missing_rule=score.missing_rule,
                min_valid=score.min_valid,
                existing_column=columns.get(f"{defaults.SCORE_PREFIX}{score.id}"),
                unavailable_items=[item_id for item_id in score.items if item_id not in by_item],
            )
        )
    return scores


def option_bounds(options: list[ResponseOption]) -> tuple[float, float]:
    values = [float(option.value) for option in options]
    return min(values), max(values)


def as_text_dict(text: Text) -> dict[str, str]:
    return {DEFAULT_TEXT_KEY: text} if isinstance(text, str) else dict(text)
