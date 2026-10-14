import pandas as pd
from pydantic import BaseModel

from labcatalog.config import MissingCode, ProjectConfig
from labcatalog.resolve import Catalog
from labcatalog.sources import LoadedDataset


class VariableSummary(BaseModel):
    column: str
    dataset: str
    n_total: int
    n_valid: int
    missing: dict[str, int]
    value_counts: dict[str, int]
    unexpected_values: dict[str, int] = {}
    mean: float | None = None
    sd: float | None = None
    minimum: float | None = None
    maximum: float | None = None


class ScoreSummary(BaseModel):
    key: str
    dataset: str
    n_valid: int
    mean: float | None = None
    sd: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    histogram: list[tuple[float, float, int]] = []
    alpha: float | None = None


class DatasetSummary(BaseModel):
    dataset: str
    n_rows: int
    n_excluded: int
    collected_by_month: dict[str, int] = {}
    snapshot_date: str | None = None


class WaveRetention(BaseModel):
    study: str
    reporter: str
    wave: str
    n: int
    n_from_previous: int | None = None
    n_families_complete: int | None = None


class Summary(BaseModel):
    variables: list[VariableSummary]
    scores: list[ScoreSummary]
    datasets: list[DatasetSummary]
    retention: list[WaveRetention]


def summarize_variable(values: pd.Series, missing_codes: list[MissingCode]) -> VariableSummary:
    raise NotImplementedError


def cronbach_alpha(items: pd.DataFrame) -> float | None:
    raise NotImplementedError


def collected_by_month(dates: pd.Series, date_format: str) -> dict[str, int]:
    raise NotImplementedError


def retention(datasets: dict[str, LoadedDataset], config: ProjectConfig) -> list[WaveRetention]:
    raise NotImplementedError


def summarize(
    catalog: Catalog,
    datasets: dict[str, LoadedDataset],
    scores: dict[str, pd.DataFrame],
    config: ProjectConfig,
) -> Summary:
    raise NotImplementedError
