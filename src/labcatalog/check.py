import pandas as pd
from pydantic import BaseModel

from labcatalog.config import ProjectConfig
from labcatalog.issues import Issue
from labcatalog.resolve import Catalog
from labcatalog.sources import LoadedDataset


class CheckReport(BaseModel):
    issues: list[Issue] = []

    def has_errors(self) -> bool:
        raise NotImplementedError


def check_columns(catalog: Catalog, datasets: dict[str, LoadedDataset]) -> list[Issue]:
    raise NotImplementedError


def check_values(
    catalog: Catalog, datasets: dict[str, LoadedDataset], config: ProjectConfig
) -> list[Issue]:
    raise NotImplementedError


def check_ids(datasets: dict[str, LoadedDataset], config: ProjectConfig) -> list[Issue]:
    raise NotImplementedError


def check_identifier_columns(datasets: dict[str, LoadedDataset]) -> list[Issue]:
    raise NotImplementedError


def check_score_agreement(
    catalog: Catalog, datasets: dict[str, LoadedDataset], scores: dict[str, pd.DataFrame]
) -> list[Issue]:
    raise NotImplementedError


def check_project(
    catalog: Catalog,
    datasets: dict[str, LoadedDataset],
    scores: dict[str, pd.DataFrame],
    config: ProjectConfig,
) -> CheckReport:
    raise NotImplementedError
