from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from labcatalog import defaults
from labcatalog.data.resolve import ResolvedVariable, numbers_in_range
from labcatalog.pipeline import CatalogResult

NUMBER = "number"
CHOICE = "choice"
ITEM_PREFIX = "item:"


@dataclass
class Sample:
    datasets: list[str]
    people: list[str]
    # Rows left out because their ID or group repeats within a file.
    ambiguous: int


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
    found = []
    for name in datasets:
        keys = link_keys(result, name)
        found.append(set(keys[linkable(keys)]))
    ambiguous = sum(
        int(link_keys(result, name).dropna().duplicated(keep=False).sum()) for name in datasets
    )
    if not found:
        people: set[str] = set()
    elif intersect:
        people = set.intersection(*found)
    else:
        people = set().union(*found)
    return Sample(list(datasets), sorted(people), ambiguous)


def item_key(variable: ResolvedVariable) -> str:
    return f"{ITEM_PREFIX}{variable.instrument_id}.{variable.item_id}@{variable.dataset}"


def item_variable(result: CatalogResult, key: str) -> ResolvedVariable:
    return next(v for v in result.catalog.variables if item_key(v) == key)


def item_numbers(result: CatalogResult, variable: ResolvedVariable) -> pd.Series:
    # Only answers that count: a listed option, or a number within the item's range.
    numbers = result.datasets[variable.dataset].numbers(variable.column)
    if variable.type == CHOICE:
        return numbers.where(numbers.isin([float(o.value) for o in variable.response_options]))
    return numbers.where(numbers_in_range(numbers, variable))


def number_items(result: CatalogResult, datasets: list[str]) -> list[ResolvedVariable]:
    # Number items analyse as they are, like a score: features of other modalities, ages, counts.
    return [
        v
        for name in datasets
        for v in result.catalog.variables_for(name)
        if v.type == NUMBER and v.column in result.datasets[name].frame.columns
    ]


def instrument_of(key: str) -> str:
    return key.removeprefix(ITEM_PREFIX).split(".", 1)[0]


def row_values(result: CatalogResult, key: str) -> np.ndarray:
    # A score or an item, one value per row of its dataset.
    if key.startswith(ITEM_PREFIX):
        return item_numbers(result, item_variable(result, key)).to_numpy(dtype=float)
    return result.scores[key.rsplit("@", 1)[1]][key].to_numpy(dtype=float)


def values(result: CatalogResult, sample: Sample, key: str) -> pd.Series:
    keys = link_keys(result, key.rsplit("@", 1)[1])
    keep = linkable(keys)
    found = row_values(result, key)[keep]
    return pd.Series(found, index=keys.to_numpy()[keep]).reindex(sample.people)


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
