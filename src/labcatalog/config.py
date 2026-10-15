from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from labcatalog import defaults
from labcatalog.schema import StrictModel


class ProjectInfo(StrictModel):
    name: str


class Vocab(StrictModel):
    modalities: list[str] = list(defaults.DEFAULT_MODALITIES)
    reporters: list[str] = []
    targets: list[str] = []


class MissingCode(StrictModel):
    code: int | float | str
    label: str


class Defaults(StrictModel):
    id_column: str = defaults.ID_COLUMN
    date_format: str = defaults.DATE_FORMAT


class GroupConfig(StrictModel):
    name: str
    from_id: str | None = None


class IdConfig(StrictModel):
    pattern: str | None = None
    group: GroupConfig | None = None


class WaveConfig(StrictModel):
    start: date | None = None
    end: date | None = None


class StudyConfig(StrictModel):
    label: str | None = None
    waves: dict[str, WaveConfig] = {}


class DatasetConfig(StrictModel):
    name: str
    modality: str
    study: str
    wave: str
    reporter: str
    source: Literal["csv"]
    path: str | None = None
    url: str | None = None
    table: str | None = None
    id_column: str | None = None
    group_column: str | None = None
    date_column: str | None = None
    snapshot_date: date | None = None
    missing_codes: list[MissingCode] | None = None
    custom: dict[str, Any] = {}


class CustomFieldDef(StrictModel):
    name: str
    label: str | None = None
    applies_to: Literal["instrument", "administration", "dataset"]
    type: Literal["text", "number", "date", "choice", "tags"]
    choices: list[str] | None = None


class BrowseConfig(StrictModel):
    facets: list[str] | None = None


class ReferencesConfig(StrictModel):
    root: str | None = None


class StatsConfig(StrictModel):
    correlate_by: str = defaults.CORRELATE_BY


class ProjectConfig(StrictModel):
    schema_version: int = defaults.SCHEMA_VERSION
    project: ProjectInfo
    vocab: Vocab = Field(default_factory=Vocab)
    missing_codes: list[MissingCode] = []
    defaults: Defaults = Field(default_factory=Defaults)
    ids: IdConfig = Field(default_factory=IdConfig)
    studies: dict[str, StudyConfig] = {}
    datasets: list[DatasetConfig] = []
    custom_fields: list[CustomFieldDef] = []
    browse: BrowseConfig = Field(default_factory=BrowseConfig)
    references: ReferencesConfig = Field(default_factory=ReferencesConfig)
    exclusions: str | None = None
    stats: StatsConfig = Field(default_factory=StatsConfig)


def load_config(path: Path) -> ProjectConfig:
    raise NotImplementedError


def dataset_by_name(config: ProjectConfig, name: str) -> DatasetConfig:
    return next(dataset for dataset in config.datasets if dataset.name == name)


def missing_codes_for(config: ProjectConfig, dataset: DatasetConfig) -> list[MissingCode]:
    return dataset.missing_codes if dataset.missing_codes is not None else config.missing_codes


def missing_labels_for(config: ProjectConfig, dataset: DatasetConfig) -> dict[str, str]:
    # Blank cells always count as missing, whether or not a code for them is declared.
    labels = {"": defaults.BLANK_LABEL}
    labels.update({str(m.code): m.label for m in missing_codes_for(config, dataset)})
    return labels


def id_column_for(config: ProjectConfig, dataset: DatasetConfig) -> str:
    return dataset.id_column or config.defaults.id_column
