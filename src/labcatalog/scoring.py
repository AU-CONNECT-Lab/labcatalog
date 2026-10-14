import pandas as pd

from labcatalog.config import MissingCode, ProjectConfig
from labcatalog.resolve import Catalog, ResolvedScore
from labcatalog.sources import LoadedDataset


def mask_missing(values: pd.Series, missing_codes: list[MissingCode]) -> pd.Series:
    raise NotImplementedError


def to_numeric(values: pd.Series) -> pd.Series:
    raise NotImplementedError


def reverse(values: pd.Series, low: float, high: float) -> pd.Series:
    raise NotImplementedError


def compute_score(frame: pd.DataFrame, score: ResolvedScore) -> pd.Series:
    raise NotImplementedError


def compute_scores(
    catalog: Catalog, datasets: dict[str, LoadedDataset], config: ProjectConfig
) -> dict[str, pd.DataFrame]:
    raise NotImplementedError
