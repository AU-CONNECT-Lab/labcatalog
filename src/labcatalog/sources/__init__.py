from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

from labcatalog.config import DatasetConfig, id_column_for
from labcatalog.data.ids import group_ids
from labcatalog.exceptions import DataSourceError
from labcatalog.paths import expand_path
from labcatalog.project import Project
from labcatalog.sources.csv_source import CsvSource
from labcatalog.sources.folder_source import FolderSource


class DataSource(Protocol):
    def read(self, dataset: DatasetConfig, project_root: Path, id_column: str) -> pd.DataFrame: ...


SOURCES: dict[str, DataSource] = {"csv": CsvSource(), "folder": FolderSource()}


@dataclass
class LoadedDataset:
    config: DatasetConfig
    frame: pd.DataFrame
    id_column: str
    group: pd.Series | None
    source_path: Path | None
    # Every wave named in a file that holds several, before this dataset's rows were taken.
    file_waves: set[str] | None = None
    numeric_cache: dict[str, pd.Series] = field(default_factory=dict, repr=False)

    def numbers(self, column: str) -> pd.Series:
        # Converting text to numbers is the slowest step on wide data, so each column is done once.
        if column not in self.numeric_cache:
            self.numeric_cache[column] = pd.to_numeric(self.frame[column], errors="coerce")
        return self.numeric_cache[column]


def get_source(name: str) -> DataSource:
    return SOURCES[name]


def load_dataset(project: Project, dataset: DatasetConfig) -> LoadedDataset:
    config = project.config
    id_column = id_column_for(config, dataset)
    frame = get_source(dataset.source).read(dataset, project.root, id_column)
    file_waves = None
    if dataset.wave_column:
        if dataset.wave_column not in frame:
            raise DataSourceError(f"{dataset.name}: no wave column '{dataset.wave_column}'")
        file_waves = set(frame[dataset.wave_column])
        # The index keeps each row's place in the file, so problems point at the right line.
        frame = frame[frame[dataset.wave_column] == dataset.wave]
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
        file_waves=file_waves,
    )


def load_datasets(project: Project) -> dict[str, LoadedDataset]:
    return {dataset.name: load_dataset(project, dataset) for dataset in project.config.datasets}
