from datetime import date
from typing import Any, Literal

from pydantic import Field

from labcatalog import defaults
from labcatalog.schema import StrictModel


class ProjectInfo(StrictModel):
    name: str


class Vocab(StrictModel):
    modalities: list[str] = list(defaults.DEFAULT_MODALITIES)
    # How a modality reads in tables and prose; the plain word when not given.
    modality_labels: dict[str, str] = {}
    reporters: list[str] = []
    targets: list[str] = []

    def modality_label(self, modality: str) -> str:
        return self.modality_labels.get(modality, modality)


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


class RosterConfig(StrictModel):
    # One row per person; where each person's group is read from when the ID holds none.
    path: str
    id_column: str | None = None
    group_column: str | None = None
    # Each person's role, one of vocab.reporters, held against the reporter of their datasets.
    role_column: str | None = None
    # The demographics instrument that describes the other columns, mapped in maps/roster.csv.
    instrument: str | None = None


class WaveConfig(StrictModel):
    start: date | None = None
    end: date | None = None


class Milestone(StrictModel):
    name: str
    date: date


class StudyConfig(StrictModel):
    label: str | None = None
    description: str | None = None
    reference: str | None = None
    waves: dict[str, WaveConfig] = {}
    milestones: list[Milestone] = []
    custom: dict[str, Any] = {}


class DatasetConfig(StrictModel):
    name: str
    modality: str
    study: str
    wave: str
    reporter: str
    source: Literal["csv", "folder"]
    path: str | None = None
    # A folder dataset's files, with {id} where each file's path holds the ID.
    files: str | None = None
    id_column: str | None = None
    # Who filled in each row, when the ID is the person the row is about.
    respondent_column: str | None = None
    date_column: str | None = None
    # In a file holding several waves, the column that names each row's wave.
    wave_column: str | None = None
    # How the wave column writes this dataset's wave, when not as `wave`.
    wave_value: str | None = None
    # The column map in maps/ this dataset reads, when it shares one with other datasets.
    map: str | None = None
    snapshot_date: date | None = None
    missing_codes: list[MissingCode] | None = None
    custom: dict[str, Any] = {}

    def wave_in_file(self) -> str:
        return self.wave if self.wave_value is None else self.wave_value

    def map_name(self) -> str:
        return self.name if self.map is None else self.map

    def map_file(self) -> str:
        return f"{defaults.MAPS_DIR}/{self.map_name()}.csv"


class CustomFieldDef(StrictModel):
    name: str
    label: str | None = None
    applies_to: Literal["instrument", "score", "item", "administration", "dataset", "study"]
    type: Literal["text", "number", "date", "choice", "tags"]
    choices: list[str] | None = None


class BrowseConfig(StrictModel):
    facets: list[str] | None = None


class ReferencesConfig(StrictModel):
    root: str | None = None


class FreedParameter(StrictModel):
    # An exception to an equality constraint of an invariance test, chosen by the user.
    instrument: str
    item: str
    parameter: Literal["loading", "threshold", "intercept"]
    # waves, reporters, or the grouping item as instrument.item.
    across: str = "waves"


CORRELATIONS = {"pearson": "Pearson r", "spearman": "Spearman's ρ"}


class StatsConfig(StrictModel):
    correlate_by: str = defaults.CORRELATE_BY
    # Decimal places of the numbers in tables and paragraphs; p values keep three.
    decimals: int = Field(defaults.DECIMALS, ge=1, le=4)
    # Factor models: items as ordered categories (WLSMV) or as continuous (ML, robust MLR); the
    # default the pages start from.
    cfa_estimator: Literal["wlsmv", "ml", "mlr"] = "wlsmv"
    # Two groups: Welch's t test with d from the mean of the two variances, or Student's with
    # the pooled SD, as JASP gives it by default.
    t_test: Literal["welch", "student"] = "welch"
    # Correlations between scores and variables; item-rest and regression stay Pearson.
    correlation: Literal["pearson", "spearman"] = "pearson"
    # Missing values: each analysis on everyone with values, or multiple imputation in R (mice).
    missing: Literal["available", "impute"] = "available"
    imputations: int = Field(defaults.IMPUTATIONS, ge=2, le=500)
    seed: int = defaults.SEED
    invariance_free: list[FreedParameter] = []

    def coefficient(self) -> str:
        return CORRELATIONS[self.correlation]


class LlmConfig(StrictModel):
    # The lab's provider and model; keys and a local server's address stay on each computer.
    provider: Literal["anthropic", "openai", "gemini", "local"] = defaults.LLM_PROVIDER
    model: str | None = None
    # What a cleaning script's model sees of a raw file: each column's values or its first rows.
    raw_data: Literal["values", "rows"] = "values"


class PrepareStep(StrictModel):
    name: str
    run: str
    inputs: list[str] = []
    outputs: list[str]


class ProjectConfig(StrictModel):
    schema_version: int = defaults.SCHEMA_VERSION
    project: ProjectInfo
    vocab: Vocab = Field(default_factory=Vocab)
    missing_codes: list[MissingCode] = []
    defaults: Defaults = Field(default_factory=Defaults)
    ids: IdConfig = Field(default_factory=IdConfig)
    roster: RosterConfig | None = None
    studies: dict[str, StudyConfig] = {}
    datasets: list[DatasetConfig] = []
    custom_fields: list[CustomFieldDef] = []
    browse: BrowseConfig = Field(default_factory=BrowseConfig)
    references: ReferencesConfig = Field(default_factory=ReferencesConfig)
    exclusions: str | None = None
    stats: StatsConfig = Field(default_factory=StatsConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    prepare: list[PrepareStep] = []
    # Runs each prepare step through datalad run, which records it in the dataset's history.
    prepare_with: Literal["datalad"] | None = None
    # Template of each instrument's Measures paragraph, in place of the built-in one.
    measures: str | None = None
    # Template of each study's Participants paragraph, in place of the built-in one.
    participants: str | None = None


def dataset_by_name(config: ProjectConfig, name: str) -> DatasetConfig:
    return next(dataset for dataset in config.datasets if dataset.name == name)


def map_name_of(config: ProjectConfig, name: str) -> str:
    # The roster is no listed dataset and reads maps/roster.csv.
    found = next((dataset for dataset in config.datasets if dataset.name == name), None)
    return name if found is None else found.map_name()


def map_sharers(config: ProjectConfig, name: str) -> list[str]:
    # The other datasets that read the same column map.
    shared = map_name_of(config, name)
    return [d.name for d in config.datasets if d.name != name and d.map_name() == shared]


def missing_codes_for(config: ProjectConfig, dataset: DatasetConfig) -> list[MissingCode]:
    return dataset.missing_codes if dataset.missing_codes is not None else config.missing_codes


def missing_labels_for(config: ProjectConfig, dataset: DatasetConfig) -> dict[str, str]:
    # Blank cells always count as missing, whether or not a code for them is declared.
    labels = {"": defaults.BLANK_LABEL}
    labels.update({str(m.code): m.label for m in missing_codes_for(config, dataset)})
    return labels


def id_column_for(config: ProjectConfig, dataset: DatasetConfig) -> str:
    return dataset.id_column or config.defaults.id_column


def roster_dataset(config: ProjectConfig) -> DatasetConfig:
    # The roster read like a dataset, belonging to no study or wave.
    roster = config.roster
    return DatasetConfig(
        name=defaults.ROSTER,
        modality="",
        study="",
        wave="",
        reporter="",
        source="csv",
        path=roster.path,
        id_column=roster.id_column,
    )
