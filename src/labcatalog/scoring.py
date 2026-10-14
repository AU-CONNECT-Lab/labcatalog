import numpy as np
import pandas as pd

from labcatalog.resolve import Catalog, ResolvedScore
from labcatalog.sources import LoadedDataset


def item_values(values: pd.Series, valid: list[float]) -> pd.Series:
    # Only real response options count; missing codes, blanks and stray values become NA.
    numbers = pd.to_numeric(values, errors="coerce")
    return numbers.where(numbers.isin(valid))


def reverse(values: pd.Series, low: float, high: float) -> pd.Series:
    return low + high - values


def compute_score(frame: pd.DataFrame, score: ResolvedScore) -> pd.Series:
    if score.unavailable_items or any(column not in frame for column in score.columns):
        return pd.Series(np.nan, index=frame.index, dtype=float)
    items = pd.DataFrame(
        {column: item_values(frame[column], score.valid_values[column]) for column in score.columns}
    )
    if not score.reversed_in_data:
        for column in score.reverse_columns:
            low, high = score.reverse_bounds[column]
            items[column] = reverse(items[column], low, high)

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
            {score.key: compute_score(loaded.frame, score) for score in catalog.scores_for(name)},
            index=loaded.frame.index,
        )
        for name, loaded in datasets.items()
    }
