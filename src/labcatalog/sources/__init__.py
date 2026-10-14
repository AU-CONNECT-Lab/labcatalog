from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from labcatalog.config import DatasetConfig, id_column_for
from labcatalog.exceptions import DataSourceError
from labcatalog.ids import family_ids, load_exclusions
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
    family: pd.Series | None
    source_path: Path | None
    n_excluded: int = 0


def get_source(name: str) -> DataSource:
    return SOURCES[name]


def load_dataset(project: Project, dataset: DatasetConfig, exclusions: set[str]) -> LoadedDataset:
    config = project.config
    frame = get_source(dataset.source).read(dataset, project.root)
    id_column = id_column_for(config, dataset)
    if id_column not in frame:
        raise DataSourceError(f"{dataset.name}: no ID column '{id_column}'")
    ids = frame[id_column]

    family = None
    if dataset.family_column:
        if dataset.family_column not in frame:
            raise DataSourceError(f"{dataset.name}: no family column '{dataset.family_column}'")
        family = frame[dataset.family_column]
    elif config.ids.family_from_id:
        family = family_ids(ids, config.ids.family_from_id)

    excluded = ids.isin(exclusions)
    if family is not None:
        excluded |= family.isin(exclusions)
    keep = ~excluded
    frame = frame[keep].reset_index(drop=True)
    return LoadedDataset(
        config=dataset,
        frame=frame,
        id_column=id_column,
        family=None if family is None else family[keep].reset_index(drop=True),
        source_path=expand_path(dataset.path, project.root) if dataset.path else None,
        n_excluded=int(excluded.sum()),
    )


def load_datasets(project: Project) -> dict[str, LoadedDataset]:
    exclusions: set[str] = set()
    if project.config.exclusions:
        exclusions = load_exclusions(expand_path(project.config.exclusions, project.root))
    return {
        dataset.name: load_dataset(project, dataset, exclusions)
        for dataset in project.config.datasets
    }
