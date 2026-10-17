import numpy as np
import pandas as pd

from labcatalog.data.resolve import Catalog, ResolvedScore
from labcatalog.sources import LoadedDataset


def reverse(values: pd.Series, low: float, high: float) -> pd.Series:
    return low + high - values


def scorable(loaded: LoadedDataset, score: ResolvedScore) -> bool:
    return not score.unavailable_items and all(c in loaded.frame for c in score.columns)


def raw_items(loaded: LoadedDataset, score: ResolvedScore) -> pd.DataFrame:
    return pd.DataFrame({c: loaded.answers(c, score.valid_values[c]) for c in score.columns})


def score_items(loaded: LoadedDataset, score: ResolvedScore) -> pd.DataFrame:
    items = raw_items(loaded, score)
    if not score.reversed_in_data:
        for column in score.reverse_columns:
            low, high = score.reverse_bounds[column]
            items[column] = reverse(items[column], low, high)
    return items


def compute_score(loaded: LoadedDataset, score: ResolvedScore) -> pd.Series:
    if not scorable(loaded, score):
        return pd.Series(np.nan, index=loaded.frame.index, dtype=float)
    items = score_items(loaded, score)
    k = len(score.columns)
    n_valid = items.notna().sum(axis=1)
    if score.missing_rule == "complete":
        enough = n_valid == k
    else:
        enough = n_valid >= (score.min_valid or k)

    if score.missing_rule == "zero":
        total = items.fillna(0).sum(axis=1)
        value = total if score.method == "sum" else total / k
    elif score.method == "mean":
        value = items.mean(axis=1)
    elif score.missing_rule == "prorate":
        value = items.mean(axis=1) * k
    else:
        value = items.sum(axis=1)
    return value.where(enough)


def compute_scores(catalog: Catalog, datasets: dict[str, LoadedDataset]) -> dict[str, pd.DataFrame]:
    return {
        name: pd.DataFrame(
            {score.key: compute_score(loaded, score) for score in catalog.scores_for(name)},
            index=loaded.frame.index,
        )
        for name, loaded in datasets.items()
    }
