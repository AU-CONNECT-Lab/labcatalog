from datetime import date

import numpy as np
import pandas as pd
from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.config import ProjectConfig, missing_labels_for
from labcatalog.resolve import Catalog, ResolvedScore, ResolvedVariable
from labcatalog.scoring import item_values, scorable, score_items
from labcatalog.sources import LoadedDataset


class VariableSummary(BaseModel):
    column: str
    dataset: str
    n_total: int
    n_valid: int
    missing: dict[str, int]
    value_counts: dict[str, int]
    n_unexpected: int = 0
    mean: float | None = None
    sd: float | None = None
    minimum: float | None = None
    maximum: float | None = None


class ItemTotal(BaseModel):
    column: str
    r: float | None
    alpha_if_deleted: float | None


class ScoreSummary(BaseModel):
    key: str
    dataset: str
    n_valid: int
    mean: float | None = None
    sd: float | None = None
    median: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    possible_range: tuple[float, float]
    histogram: list[tuple[float, float, int]] = []
    alpha: float | None = None
    n_complete: int = 0
    item_total: list[ItemTotal] = []
    item_columns: list[str] = []
    item_correlations: list[list[float | None]] = []


class InstrumentCompleteness(BaseModel):
    instrument_id: str
    n_items: int
    complete: int
    partial: int
    empty: int


class DatasetSummary(BaseModel):
    dataset: str
    n_rows: int
    n_ids: int
    n_groups: int | None = None
    first_date: date | None = None
    last_date: date | None = None
    collected_by_month: dict[str, int] = {}
    snapshot_date: date | None = None
    missing_totals: dict[str, int] = {}
    n_unexpected: int = 0
    completeness: list[InstrumentCompleteness] = []


class WaveRetention(BaseModel):
    study: str
    reporter: str
    wave: str
    n: int
    n_from_previous: int | None = None
    n_new: int | None = None


class WaveGroups(BaseModel):
    study: str
    wave: str
    groups: int
    with_every_reporter: int


class Correlation(BaseModel):
    study: str
    wave: str
    keys: list[str]
    r: list[list[float | None]]
    n: list[list[int]]
    n_ambiguous: int = 0


class Summary(BaseModel):
    variables: list[VariableSummary]
    scores: list[ScoreSummary]
    datasets: list[DatasetSummary]
    retention: list[WaveRetention]
    group_name: str | None = None
    groups: list[WaveGroups] = []
    correlations: list[Correlation]


def summarize(
    catalog: Catalog,
    datasets: dict[str, LoadedDataset],
    scores: dict[str, pd.DataFrame],
    config: ProjectConfig,
) -> Summary:
    variables = [
        summarize_variable(datasets[v.dataset], v, config)
        for v in catalog.variables
        if v.column in datasets[v.dataset].frame
    ]
    return Summary(
        variables=variables,
        scores=[
            summarize_score(datasets[s.dataset], s, scores[s.dataset][s.key])
            for s in catalog.scores
        ],
        datasets=[
            summarize_dataset(loaded, catalog, variables, config) for loaded in datasets.values()
        ],
        retention=retention(datasets),
        group_name=config.ids.group.name if config.ids.group else None,
        groups=wave_groups(datasets),
        correlations=correlations(catalog, datasets, scores, config.stats.correlate_by),
    )


def summarize_variable(
    loaded: LoadedDataset, variable: ResolvedVariable, config: ProjectConfig
) -> VariableSummary:
    values = loaded.frame[variable.column]
    labels = missing_labels_for(config, loaded.config)
    missing = {label: int(values.isin([code]).sum()) for code, label in labels.items()}
    options = [option.value for option in variable.response_options]
    numbers = loaded.numbers(variable.column)
    counts = {
        str(v): int((values == v).sum()) if isinstance(v, str) else int((numbers == v).sum())
        for v in options
    }
    numeric = item_values(numbers, [float(v) for v in options if not isinstance(v, str)])
    n_valid = sum(counts.values())
    unexpected = len(values) - n_valid - sum(missing.values())
    return VariableSummary(
        column=variable.column,
        dataset=variable.dataset,
        n_total=len(values),
        n_valid=n_valid,
        missing=missing,
        value_counts=counts,
        n_unexpected=unexpected,
        **describe(numeric),
    )


def summarize_score(loaded: LoadedDataset, score: ResolvedScore, values: pd.Series) -> ScoreSummary:
    low, high = score_range(score)
    valid = values.dropna()
    summary = ScoreSummary(
        key=score.key,
        dataset=score.dataset,
        n_valid=len(valid),
        possible_range=(low, high),
        histogram=histogram(valid, low, high, integer=score.method == "sum"),
        **describe(valid),
        median=float(valid.median()) if len(valid) else None,
    )
    if scorable(loaded, score):
        items = score_items(loaded, score)
        complete = items.dropna()
        summary.n_complete = len(complete)
        summary.alpha = cronbach_alpha(complete)
        summary.item_total = item_total(complete) if summary.alpha is not None else []
        summary.item_columns = list(items.columns)
        summary.item_correlations = item_correlations(complete)
    return summary


def describe(values: pd.Series) -> dict[str, float | None]:
    values = values.dropna()
    if values.empty:
        return {"mean": None, "sd": None, "minimum": None, "maximum": None}
    return {
        "mean": float(values.mean()),
        "sd": float(values.std(ddof=1)) if len(values) > 1 else None,
        "minimum": float(values.min()),
        "maximum": float(values.max()),
    }


def score_range(score: ResolvedScore) -> tuple[float, float]:
    lows = [min(score.valid_values[column]) for column in score.columns]
    highs = [max(score.valid_values[column]) for column in score.columns]
    if score.method == "sum":
        return sum(lows), sum(highs)
    return min(lows), max(highs)


def histogram(
    values: pd.Series, low: float, high: float, integer: bool
) -> list[tuple[float, float, int]]:
    if integer and high - low <= defaults.HISTOGRAM_BINS * 2:
        # One bin per whole number, so a prorated 7.2 lands with the 7s.
        edges = np.arange(low - 0.5, high + 1.5, 1.0)
    else:
        edges = np.linspace(low, high, defaults.HISTOGRAM_BINS + 1)
    counts, _ = np.histogram(values, bins=edges)
    return [
        (float(a), float(b), int(c)) for a, b, c in zip(edges[:-1], edges[1:], counts, strict=True)
    ]


def cronbach_alpha(items: pd.DataFrame) -> float | None:
    complete = items.dropna()
    if complete.shape[1] < 2 or len(complete) < defaults.MIN_CORRELATION_N:
        return None
    return alpha_from_cov(np.cov(complete.to_numpy(dtype=float), rowvar=False))


def alpha_from_cov(cov: np.ndarray) -> float | None:
    k = cov.shape[0]
    total = cov.sum()
    if k < 2 or total == 0:
        return None
    return float(k / (k - 1) * (1 - np.trace(cov) / total))


def item_total(complete: pd.DataFrame) -> list[ItemTotal]:
    # Everything follows from one covariance matrix, so the data is read only once.
    k = complete.shape[1]
    if k < 3:
        return []
    cov = np.cov(complete.to_numpy(dtype=float), rowvar=False)
    rows = []
    for i, column in enumerate(complete.columns):
        rest = [j for j in range(k) if j != i]
        rest_cov = cov[np.ix_(rest, rest)]
        spread = cov[i, i] * rest_cov.sum()
        r = cov[i, rest].sum() / np.sqrt(spread) if spread > 0 else None
        rows.append(
            ItemTotal(
                column=column,
                r=None if r is None else float(r),
                alpha_if_deleted=alpha_from_cov(rest_cov),
            )
        )
    return rows


def item_correlations(complete: pd.DataFrame) -> list[list[float | None]]:
    # Spearman suits ordinal answers; items are already reverse-scored, so a negative r stands out.
    if complete.shape[1] < 2 or len(complete) < defaults.MIN_CORRELATION_N:
        return []
    ranks = complete.rank().to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        matrix = np.corrcoef(ranks, rowvar=False)
    diagonal = np.diag_indices_from(matrix)
    matrix[diagonal] = np.where(np.isnan(matrix[diagonal]), np.nan, 1.0)
    return [[None if np.isnan(r) else float(r) for r in row] for row in matrix]


def summarize_dataset(
    loaded: LoadedDataset,
    catalog: Catalog,
    variables: list[VariableSummary],
    config: ProjectConfig,
) -> DatasetSummary:
    name = loaded.config.name
    frame = loaded.frame
    mine = [v for v in variables if v.dataset == name]
    missing_totals: dict[str, int] = {}
    for summary in mine:
        for label, count in summary.missing.items():
            missing_totals[label] = missing_totals.get(label, 0) + count
    dates = None
    if loaded.config.date_column and loaded.config.date_column in frame:
        dates = pd.to_datetime(
            frame[loaded.config.date_column], format=config.defaults.date_format, errors="coerce"
        ).dropna()
    return DatasetSummary(
        dataset=name,
        n_rows=len(frame),
        n_ids=int(frame[loaded.id_column].nunique()),
        n_groups=None if loaded.group is None else int(loaded.group.nunique()),
        first_date=dates.min().date() if dates is not None and len(dates) else None,
        last_date=dates.max().date() if dates is not None and len(dates) else None,
        collected_by_month=collected_by_month(dates) if dates is not None else {},
        snapshot_date=loaded.config.snapshot_date,
        missing_totals=missing_totals,
        n_unexpected=sum(v.n_unexpected for v in mine),
        completeness=completeness(loaded, catalog, config),
    )


def collected_by_month(dates: pd.Series) -> dict[str, int]:
    counts = dates.dt.strftime("%Y-%m").value_counts()
    return {month: int(counts[month]) for month in sorted(counts.index)}


def completeness(
    loaded: LoadedDataset, catalog: Catalog, config: ProjectConfig
) -> list[InstrumentCompleteness]:
    frame = loaded.frame
    by_instrument: dict[str, list[pd.Series]] = {}
    for variable in catalog.variables_for(loaded.config.name):
        if variable.column not in frame:
            continue
        options = [str(option.value) for option in variable.response_options]
        values = frame[variable.column]
        numeric = loaded.numbers(variable.column)
        valid = values.isin(options) | numeric.isin([float(v) for v in options if is_number(v)])
        by_instrument.setdefault(variable.instrument_id, []).append(valid)
    rows = []
    for instrument_id, columns in by_instrument.items():
        answered = pd.concat(columns, axis=1).sum(axis=1)
        k = len(columns)
        rows.append(
            InstrumentCompleteness(
                instrument_id=instrument_id,
                n_items=k,
                complete=int((answered == k).sum()),
                partial=int(((answered > 0) & (answered < k)).sum()),
                empty=int((answered == 0).sum()),
            )
        )
    return rows


def retention(datasets: dict[str, LoadedDataset]) -> list[WaveRetention]:
    groups: dict[tuple[str, str], list[LoadedDataset]] = {}
    for loaded in datasets.values():
        groups.setdefault((loaded.config.study, loaded.config.reporter), []).append(loaded)
    rows = []
    for (study, reporter), members in groups.items():
        previous: set[str] | None = None
        for loaded in sorted(members, key=lambda d: wave_order(d.config.wave)):
            ids = set(loaded.frame[loaded.id_column])
            rows.append(
                WaveRetention(
                    study=study,
                    reporter=reporter,
                    wave=loaded.config.wave,
                    n=len(ids),
                    n_from_previous=None if previous is None else len(ids & previous),
                    n_new=None if previous is None else len(ids - previous),
                )
            )
            previous = ids
    return rows


def wave_groups(datasets: dict[str, LoadedDataset]) -> list[WaveGroups]:
    waves: dict[tuple[str, str], dict[str, set[str]]] = {}
    for loaded in datasets.values():
        if loaded.group is None:
            continue
        reporters = waves.setdefault((loaded.config.study, loaded.config.wave), {})
        reporters.setdefault(loaded.config.reporter, set()).update(loaded.group.dropna())
    rows = []
    for (study, wave), reporters in sorted(waves.items(), key=lambda kv: wave_order(kv[0][1])):
        sets = list(reporters.values())
        rows.append(
            WaveGroups(
                study=study,
                wave=wave,
                groups=len(set().union(*sets)),
                with_every_reporter=len(set.intersection(*sets)),
            )
        )
    return rows


def correlations(
    catalog: Catalog,
    datasets: dict[str, LoadedDataset],
    scores: dict[str, pd.DataFrame],
    correlate_by: str,
) -> list[Correlation]:
    if correlate_by == "none":
        return []
    waves: dict[tuple[str, str], dict[str, pd.Series]] = {}
    ambiguous: dict[tuple[str, str], set] = {}
    for score in catalog.scores:
        loaded = datasets[score.dataset]
        values = scores[score.dataset][score.key]
        if values.notna().sum() == 0:
            continue
        by_id = correlate_by == "id" or loaded.group is None
        link = loaded.frame[loaded.id_column] if by_id else loaded.group
        linked = pd.Series(values.to_numpy(), index=link.to_numpy())
        # A link value that repeats within a file (two children in one family) is ambiguous.
        repeated = linked.index.duplicated(keep=False)
        wave_key = (loaded.config.study, loaded.config.wave)
        ambiguous.setdefault(wave_key, set()).update(linked.index[repeated])
        waves.setdefault(wave_key, {})[score.key] = linked[~repeated & linked.index.notna()]
    rows = []
    for (study, wave), series in sorted(waves.items(), key=lambda kv: wave_order(kv[0][1])):
        if len(series) < 2:
            continue
        table = pd.DataFrame(series)
        present = table.notna().astype(float)
        pairs = present.T @ present
        matrix = table.corr(min_periods=defaults.MIN_CORRELATION_N)
        rows.append(
            Correlation(
                study=study,
                wave=wave,
                keys=list(table.columns),
                r=[[None if pd.isna(r) else float(r) for r in row] for row in matrix.to_numpy()],
                n=[[int(n) for n in row] for row in pairs.to_numpy()],
                n_ambiguous=len(ambiguous.get((study, wave), set())),
            )
        )
    return rows


def wave_order(wave: str) -> tuple[int, float | str]:
    return (0, float(wave)) if is_number(wave) else (1, wave)


def is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
