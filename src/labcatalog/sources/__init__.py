from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

from labcatalog.config import DatasetConfig, id_column_for
from labcatalog.data import id_map
from labcatalog.data.ids import group_ids
from labcatalog.exceptions import DataSourceError
from labcatalog.paths import expand_path
from labcatalog.project import Project
from labcatalog.sources.csv_source import CsvSource, read_csv
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
    # The IDs as the file writes them, before id_map.csv corrects them.
    original_ids: pd.Series | None = None
    numeric_cache: dict[str, pd.Series] = field(default_factory=dict, repr=False)
    answer_cache: dict[tuple, pd.Series] = field(default_factory=dict, repr=False)

    def respondents(self) -> pd.Series:
        return self.frame[self.config.respondent_column or self.id_column]

    def numbers(self, column: str) -> pd.Series:
        # Converting text to numbers is the slowest step on wide data, so each column is done once.
        if column not in self.numeric_cache:
            self.numeric_cache[column] = pd.to_numeric(self.frame[column], errors="coerce")
        return self.numeric_cache[column]

    def answers(self, column: str, valid: list[float]) -> pd.Series:
        # Only real response options count; missing codes, blanks and stray values become NA.
        key = (column, *valid)
        if key not in self.answer_cache:
            numbers = self.numbers(column)
            self.answer_cache[key] = numbers.where(numbers.isin(valid))
        return self.answer_cache[key]


def get_source(name: str) -> DataSource:
    return SOURCES[name]


@dataclass
class Roster:
    frame: pd.DataFrame
    id_column: str
    group_column: str | None
    path: Path

    def groups(self) -> pd.Series:
        # A person listed twice has no known group; the checks report them.
        ids = self.frame[self.id_column]
        listed = self.frame[(ids != "") & ~ids.duplicated(keep=False)]
        return listed.set_index(self.id_column)[self.group_column].replace("", pd.NA)


def load_roster(project: Project) -> Roster | None:
    roster = project.config.roster
    if roster is None:
        return None
    path = expand_path(roster.path, project.root)
    frame = read_csv(path, "roster")
    id_column = roster.id_column or project.config.defaults.id_column
    for column in (id_column, roster.group_column):
        if column and column not in frame:
            raise DataSourceError(f"roster: no column '{column}' in {path}")
    return Roster(frame, id_column, roster.group_column, path)


def load_dataset(
    project: Project, dataset: DatasetConfig, groups: pd.Series | None = None
) -> LoadedDataset:
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
    if dataset.respondent_column and dataset.respondent_column not in frame:
        raise DataSourceError(f"{dataset.name}: no respondent column '{dataset.respondent_column}'")
    original = frame[id_column]
    if corrected := id_map.mapping(project.root, dataset.name):
        frame = frame.copy()
        for column in filter(None, (id_column, dataset.respondent_column)):
            frame[column] = id_map.apply(frame[column], corrected)
    ids = frame[id_column]

    group = None
    if groups is not None:
        group = ids.map(groups)
    elif config.ids.group and config.ids.group.from_id:
        group = group_ids(ids, config.ids.group.from_id)

    return LoadedDataset(
        config=dataset,
        frame=frame,
        id_column=id_column,
        group=group,
        source_path=expand_path(dataset.path, project.root) if dataset.path else None,
        file_waves=file_waves,
        original_ids=original,
    )


def load_datasets(project: Project) -> dict[str, LoadedDataset]:
    roster = load_roster(project)
    groups = roster.groups() if roster and roster.group_column else None
    return {
        dataset.name: load_dataset(project, dataset, groups) for dataset in project.config.datasets
    }
