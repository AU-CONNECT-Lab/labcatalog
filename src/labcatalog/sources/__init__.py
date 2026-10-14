from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from labcatalog.config import DatasetConfig
from labcatalog.project import Project


class DataSource(Protocol):
    def read(self, dataset: DatasetConfig, project_root: Path) -> pd.DataFrame: ...


@dataclass
class LoadedDataset:
    config: DatasetConfig
    frame: pd.DataFrame
    id_column: str
    raw_ids: pd.Series
    family: pd.Series | None
    source_path: Path | None


def get_source(name: str) -> DataSource:
    raise NotImplementedError


def load_dataset(project: Project, dataset: DatasetConfig) -> LoadedDataset:
    raise NotImplementedError


def load_datasets(project: Project) -> dict[str, LoadedDataset]:
    raise NotImplementedError
