from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

from labcatalog.config import DatasetConfig, id_column_for, roster_dataset, rosters
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
    # The scores file's columns, one row per row of the data; None when there is no such file.
    scores: pd.DataFrame | None = None
    # Every ID of the scores file, to find those the data do not have.
    score_ids: set[str] | None = None
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
    role_column: str | None = None

    def groups(self) -> pd.Series:
        # A person listed twice has no known group; the checks report them.
        ids = self.frame[self.id_column]
        listed = self.frame[(ids != "") & ~ids.duplicated(keep=False)]
        return listed.set_index(self.id_column)[self.group_column].replace("", pd.NA)

    def roles(self) -> pd.Series:
        ids = self.frame[self.id_column]
        listed = self.frame[(ids != "") & ~ids.duplicated(keep=False)]
        return listed.set_index(self.id_column)[self.role_column].str.strip()


def load_roster(project: Project, study: str) -> Roster:
    roster = project.config.studies[study].roster
    path = expand_path(roster.path, project.root)
    frame = read_csv(path, f"{study} roster")
    id_column = roster.id_column or project.config.defaults.id_column
    for column in (id_column, roster.group_column, roster.role_column):
        if column and column not in frame:
            raise DataSourceError(f"{study} roster: no column '{column}' in {path}")
    return Roster(frame, id_column, roster.group_column, path, roster.role_column)


def load_rosters(project: Project) -> dict[str, Roster]:
    return {study: load_roster(project, study) for study in rosters(project.config)}


def load_roster_datasets(project: Project) -> dict[str, LoadedDataset]:
    # Only a roster an instrument describes is read for its other columns.
    return {
        study: LoadedDataset(
            config=roster_dataset(project.config, study),
            frame=roster.frame,
            id_column=roster.id_column,
            group=None,
            source_path=roster.path,
        )
        for study, roster in load_rosters(project).items()
        if project.config.studies[study].roster.instrument
    }


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
        frame = frame[frame[dataset.wave_column] == dataset.wave_in_file()]
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
    scores, score_ids = read_scores(project, dataset, id_column, ids, corrected)

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
        scores=scores,
        score_ids=score_ids,
    )


def read_scores(
    project: Project,
    dataset: DatasetConfig,
    id_column: str,
    ids: pd.Series,
    corrected: dict[str, str],
) -> tuple[pd.DataFrame | None, set[str] | None]:
    # Before its prepare step has run the file is not there; the checks say so.
    if dataset.scores is None:
        return None, None
    path = expand_path(dataset.scores, project.root)
    if not path.is_file():
        return None, None
    table = read_csv(path, dataset.name)
    if id_column not in table:
        raise DataSourceError(
            f"{dataset.name}: the scores file {dataset.scores} has no column '{id_column}'"
        )
    table[id_column] = id_map.apply(table[id_column], corrected)
    found = set(table[id_column])
    by_id = table.drop_duplicates(id_column).set_index(id_column)
    return by_id.reindex(ids.to_numpy()).set_axis(ids.index), found


def load_datasets(project: Project) -> dict[str, LoadedDataset]:
    groups = {s: r.groups() for s, r in load_rosters(project).items() if r.group_column}
    return {
        dataset.name: load_dataset(project, dataset, groups.get(dataset.study))
        for dataset in project.config.datasets
    }
