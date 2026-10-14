from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from labcatalog.config import DatasetConfig, id_column_for
from labcatalog.exceptions import DataSourceError
from labcatalog.ids import group_ids
from labcatalog.paths import expand_path
from labcatalog.project import Project
from labcatalog.sources.csv_source import CsvSource


class DataSource(Protocol):
    def read(self, dataset: DatasetConfig, project_root: Path) -> pd.DataFrame: ...


SOURCES: dict[str, DataSource] = {"csv": CsvSource()}


@dataclass
class LoadedDataset:
    config: DatasetConfig
    frame: pd.DataFrame
    id_column: str
    group: pd.Series | None
    source_path: Path | None


def get_source(name: str) -> DataSource:
    return SOURCES[name]


def load_dataset(project: Project, dataset: DatasetConfig) -> LoadedDataset:
    config = project.config
    frame = get_source(dataset.source).read(dataset, project.root)
    id_column = id_column_for(config, dataset)
    if id_column not in frame:
        raise DataSourceError(f"{dataset.name}: no ID column '{id_column}'")
    ids = frame[id_column]

    group = None
    if dataset.group_column:
        if dataset.group_column not in frame:
            raise DataSourceError(f"{dataset.name}: no group column '{dataset.group_column}'")
        group = frame[dataset.group_column]
    elif config.ids.group and config.ids.group.from_id:
        group = group_ids(ids, config.ids.group.from_id)

    return LoadedDataset(
        config=dataset,
        frame=frame,
        id_column=id_column,
        group=group,
        source_path=expand_path(dataset.path, project.root) if dataset.path else None,
    )


def load_datasets(project: Project) -> dict[str, LoadedDataset]:
    return {dataset.name: load_dataset(project, dataset) for dataset in project.config.datasets}
