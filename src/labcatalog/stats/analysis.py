from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from scipy import stats

from labcatalog import defaults
from labcatalog.data.resolve import ResolvedVariable, numbers_in_range
from labcatalog.pipeline import CatalogResult
from labcatalog.stats.link import Links, link

NUMBER = "number"
CHOICE = "choice"
ITEM_PREFIX = "item:"
# Joins the files of a variable pooled over studies, one file of each study.
POOL = "+"
# The variable naming each person's study, when a sample pools several.
STUDY_KEY = "study"


@dataclass
class Sample:
    datasets: list[str]
    people: list[str]
    links: Links


@dataclass
class Correlation:
    n: int
    r: float | None = None
    p: float | None = None
    low: float | None = None
    high: float | None = None


@dataclass
class Fit:
    correlation: Correlation
    slope: float
    slope_se: float
    intercept: float
    intercept_se: float


def link_keys(result: CatalogResult, dataset: str) -> pd.Series:
    # People meet across files the way stats.correlate_by says; a file without the group links by ID.
    loaded = result.datasets[dataset]
    by_group = (
        result.project.config.stats.correlate_by not in ("id", "none") and loaded.group is not None
    )
    keys = loaded.group if by_group else loaded.frame[loaded.id_column]
    return keys.astype("string")


def linkable(keys: pd.Series) -> np.ndarray:
    return (keys.notna() & ~keys.duplicated(keep=False)).to_numpy()


def build_sample(result: CatalogResult, datasets: list[str], intersect: bool) -> Sample:
    # Files of several studies share no one, so "every file" means every file of one's own study.
    links = link(result.datasets, list(datasets), result.project.config.stats.correlate_by)
    by_study: dict[str, list[set[str]]] = {}
    for name in datasets:
        by_study.setdefault(study_of(result, name), []).append(set(links.rows[name].index))
    people: set[str] = set()
    for found in by_study.values():
        people |= set.intersection(*found) if intersect else set().union(*found)
    return Sample(list(datasets), sorted(people), links)


def study_of(result: CatalogResult, dataset: str) -> str:
    return result.datasets[dataset].config.study


def studies_of(result: CatalogResult, datasets: list[str]) -> list[str]:
    return list(dict.fromkeys(study_of(result, name) for name in datasets))


def pooling(result: CatalogResult, datasets: list[str]) -> bool:
    return len(studies_of(result, datasets)) > 1


def parts(key: str) -> list[str]:
    return key.rsplit("@", 1)[1].split(POOL)


def part_key(key: str, dataset: str) -> str:
    return f"{key.rsplit('@', 1)[0]}@{dataset}"


def first_key(key: str) -> str:
    # The key of one file, which a pooled variable shares its definition with.
    return part_key(key, parts(key)[0])


def pooled(result: CatalogResult, datasets: list[str], found: dict[str, str]) -> dict[str, str]:
    # Each variable that every study gives in exactly one chosen file, as one variable.
    studies = studies_of(result, datasets)
    by_base: dict[str, list[str]] = {}
    for key in found:
        by_base.setdefault(key.rsplit("@", 1)[0], []).append(key)
    joined = {}
    for keys in by_base.values():
        names = [parts(k)[0] for k in keys]
        if sorted(study_of(result, n) for n in names) == sorted(studies):
            key = f"{keys[0].rsplit('@', 1)[0]}@{POOL.join(names)}"
            joined[key] = found[keys[0]].rsplit(" (", 1)[0]
    return joined


def study_options(result: CatalogResult, sample: Sample) -> list[tuple[float, str]]:
    studies = result.project.config.studies
    return [
        (float(n), studies[s].label or s)
        for n, s in enumerate(studies_of(result, sample.datasets), start=1)
    ]


def study_numbers(result: CatalogResult, sample: Sample) -> pd.Series:
    # Pooled people are written study/key, so the study is read back from their key.
    codes = {s: float(n) for n, s in enumerate(studies_of(result, sample.datasets), start=1)}
    return pd.Series([codes[p.split("/", 1)[0]] for p in sample.people], index=sample.people)


def within(sample: Sample, datasets: list[str]) -> Sample:
    # The people of a wider sample who have a row in these datasets.
    rows = [sample.links.rows[name].index for name in datasets]
    people = [p for p in sample.people if any(p in r for r in rows)]
    return replace(sample, datasets=list(datasets), people=people)


def group_notes(result: CatalogResult, sample: Sample) -> str:
    group = result.project.config.ids.group
    name = group.name if group else "group"
    notes = []
    if sample.links.repeated:
        notes.append(
            f"{sample.links.repeated} rows are left out because their ID repeats in a file."
        )
    split = len(set(sample.links.split.values()))
    if split:
        notes.append(
            f"{split} {name} groups have several people in a file, so each person is a row and an "
            f"answer given once for the {name} counts for each of them; a multilevel model with "
            f"people nested in {name} groups allows for that."
        )
    if sample.links.crossed:
        notes.append(
            f"In {sample.links.crossed} {name} groups two files each hold several people with no "
            "one in common, so their answers do not pair across those files."
        )
    return " ".join(notes)


def aligned(sample: Sample, dataset: str, found: np.ndarray) -> pd.Series:
    rows = sample.links.rows[dataset]
    return pd.Series(found[rows.to_numpy()], index=rows.index).reindex(sample.people)


def item_key(variable: ResolvedVariable) -> str:
    return f"{ITEM_PREFIX}{variable.instrument_id}.{variable.item_id}@{variable.dataset}"


def item_variable(result: CatalogResult, key: str) -> ResolvedVariable:
    key = first_key(key)
    dataset = key.rsplit("@", 1)[1]
    return next(v for v in items_for(result, dataset) if item_key(v) == key)


def items_for(result: CatalogResult, dataset: str) -> list[ResolvedVariable]:
    return result.catalog.variables_for(dataset) + roster_items(result, dataset)


def roster_items(result: CatalogResult, dataset: str) -> list[ResolvedVariable]:
    # The study roster's columns for the people of one file, as if the file held them.
    config = result.datasets[dataset].config
    update = {
        "dataset": dataset,
        "study": config.study,
        "wave": config.wave,
        "reporter": config.reporter,
        "modality": config.modality,
    }
    return [
        v.model_copy(update=update)
        for v in result.catalog.roster_variables
        if v.study == config.study
    ]


def from_roster(result: CatalogResult, variable: ResolvedVariable) -> bool:
    roster = result.project.config.studies[variable.study].roster
    return roster is not None and roster.instrument == variable.instrument_id


def roster_numbers(result: CatalogResult, dataset: str, column: str) -> pd.Series:
    # Each row's value in its study's roster, found by its ID; someone listed twice has none.
    loaded = result.datasets[dataset]
    roster = result.rosters[loaded.config.study]
    ids = roster.frame[roster.id_column]
    once = (~ids.duplicated(keep=False)).to_numpy()
    table = pd.Series(roster.numbers(column).to_numpy()[once], index=ids[once])
    found = table.reindex(loaded.frame[loaded.id_column]).to_numpy()
    return pd.Series(found, index=loaded.frame.index)


def item_numbers(result: CatalogResult, variable: ResolvedVariable) -> pd.Series:
    # Only answers that count: a listed option, or a number within the item's range.
    numbers = (
        roster_numbers(result, variable.dataset, variable.column)
        if from_roster(result, variable)
        else result.datasets[variable.dataset].numbers(variable.column)
    )
    if variable.type == CHOICE:
        return numbers.where(numbers.isin([float(o.value) for o in variable.response_options]))
    return numbers.where(numbers_in_range(numbers, variable))


def number_items(result: CatalogResult, datasets: list[str]) -> list[ResolvedVariable]:
    # Number items analyse as they are, like a score: features of other modalities, ages, counts.
    return [
        v
        for name in datasets
        for v in items_for(result, name)
        if v.type == NUMBER
        and (from_roster(result, v) or v.column in result.datasets[name].frame.columns)
    ]


def instrument_of(key: str) -> str:
    return key.removeprefix(ITEM_PREFIX).split(".", 1)[0]


def of_instruments(found: dict[str, str], instruments: list[str]) -> dict[str, str]:
    return {k: v for k, v in found.items() if instrument_of(k) in instruments}


def row_values(result: CatalogResult, key: str) -> np.ndarray:
    # A score or an item, one value per row of its dataset.
    if key.startswith(ITEM_PREFIX):
        return item_numbers(result, item_variable(result, key)).to_numpy(dtype=float)
    return result.scores[key.rsplit("@", 1)[1]][key].to_numpy(dtype=float)


def values(result: CatalogResult, sample: Sample, key: str) -> pd.Series:
    if key == STUDY_KEY:
        return study_numbers(result, sample)
    # A pooled variable takes each person's value from the file of their own study.
    found = [aligned(sample, name, row_values(result, part_key(key, name))) for name in parts(key)]
    joined = found[0]
    for more in found[1:]:
        joined = joined.combine_first(more)
    return joined


def table(result: CatalogResult, sample: Sample, keys: list[str]) -> pd.DataFrame:
    return pd.DataFrame({key: values(result, sample, key) for key in keys})


def correlate(x: pd.Series, y: pd.Series) -> Correlation:
    both = pd.concat([x, y], axis=1).dropna()
    n = len(both)
    if (
        n < defaults.MIN_CORRELATION_N
        or both.iloc[:, 0].nunique() < 2
        or both.iloc[:, 1].nunique() < 2
    ):
        return Correlation(n)
    found = stats.pearsonr(both.iloc[:, 0], both.iloc[:, 1])
    # The Fisher z interval needs more than three people.
    low, high = found.confidence_interval() if n > 3 else (None, None)
    return Correlation(
        n,
        float(found.statistic),
        float(found.pvalue),
        None if low is None else float(low),
        None if high is None else float(high),
    )


def regress(x: pd.Series, y: pd.Series) -> Fit | None:
    correlation = correlate(x, y)
    if correlation.r is None:
        return None
    both = pd.concat([x, y], axis=1).dropna()
    found = stats.linregress(both.iloc[:, 0], both.iloc[:, 1])
    return Fit(
        correlation,
        float(found.slope),
        float(found.stderr),
        float(found.intercept),
        float(found.intercept_stderr),
    )


def correlation_matrix(frame: pd.DataFrame) -> list[list[Correlation]]:
    columns = list(frame.columns)
    return [
        [
            correlate(frame[a], frame[b]) if a != b else Correlation(int(frame[a].notna().sum()))
            for b in columns
        ]
        for a in columns
    ]


def describe(series: pd.Series) -> tuple[int, float | None, float | None]:
    found = series.dropna().to_numpy(dtype=float)
    if not len(found):
        return 0, None, None
    sd = float(np.std(found, ddof=1)) if len(found) > 1 else None
    return len(found), float(found.mean()), sd
