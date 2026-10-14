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
    n_families: int | None = None
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


class WaveFamilies(BaseModel):
    study: str
    wave: str
    families: int
    with_every_reporter: int


class Correlation(BaseModel):
    study: str
    wave: str
    keys: list[str]
    r: list[list[float | None]]
    n: list[list[int]]


class Summary(BaseModel):
    variables: list[VariableSummary]
    scores: list[ScoreSummary]
    datasets: list[DatasetSummary]
    retention: list[WaveRetention]
    families: list[WaveFamilies]
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
        families=wave_families(datasets),
        correlations=correlations(catalog, datasets, scores),
    )


def summarize_variable(
    loaded: LoadedDataset, variable: ResolvedVariable, config: ProjectConfig
) -> VariableSummary:
    values = loaded.frame[variable.column]
    labels = missing_labels_for(config, loaded.config)
    missing = {label: int(values.isin([code]).sum()) for code, label in labels.items()}
    options = [option.value for option in variable.response_options]
    numbers = pd.to_numeric(values, errors="coerce")
    counts = {
        str(v): int((values == v).sum()) if isinstance(v, str) else int((numbers == v).sum())
        for v in options
    }
    numeric = item_values(values, [float(v) for v in options if not isinstance(v, str)])
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
    if scorable(loaded.frame, score):
        complete = score_items(loaded.frame, score).dropna()
        summary.n_complete = len(complete)
        summary.alpha = cronbach_alpha(complete)
        summary.item_total = item_total(complete) if summary.alpha is not None else []
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
    return [(float(a), float(b), int(c)) for a, b, c in zip(edges[:-1], edges[1:], counts)]


def cronbach_alpha(items: pd.DataFrame) -> float | None:
    complete = items.dropna()
    k = complete.shape[1]
    if k < 2 or len(complete) < 3:
        return None
    total_variance = complete.sum(axis=1).var(ddof=1)
    if total_variance == 0:
        return None
    return float(k / (k - 1) * (1 - complete.var(axis=0, ddof=1).sum() / total_variance))


def item_total(complete: pd.DataFrame) -> list[ItemTotal]:
    if complete.shape[1] < 3:
        return []
    rows = []
    for column in complete:
        rest = complete.drop(columns=column)
        r = complete[column].corr(rest.sum(axis=1))
        rows.append(
            ItemTotal(
                column=column,
                r=None if pd.isna(r) else float(r),
                alpha_if_deleted=cronbach_alpha(rest),
            )
        )
    return rows


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
        n_families=None if loaded.family is None else int(loaded.family.nunique()),
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
        numeric = pd.to_numeric(values, errors="coerce")
        valid = values.isin(options) | numeric.isin(
            [float(v) for v in options if is_number(v)]
        )
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


def wave_families(datasets: dict[str, LoadedDataset]) -> list[WaveFamilies]:
    waves: dict[tuple[str, str], dict[str, set[str]]] = {}
    for loaded in datasets.values():
        if loaded.family is None:
            continue
        reporters = waves.setdefault((loaded.config.study, loaded.config.wave), {})
        reporters.setdefault(loaded.config.reporter, set()).update(loaded.family.dropna())
    rows = []
    for (study, wave), reporters in sorted(waves.items(), key=lambda kv: wave_order(kv[0][1])):
        sets = list(reporters.values())
        rows.append(
            WaveFamilies(
                study=study,
                wave=wave,
                families=len(set().union(*sets)),
                with_every_reporter=len(set.intersection(*sets)),
            )
        )
    return rows


def correlations(
    catalog: Catalog, datasets: dict[str, LoadedDataset], scores: dict[str, pd.DataFrame]
) -> list[Correlation]:
    waves: dict[tuple[str, str], dict[str, pd.Series]] = {}
    for score in catalog.scores:
        loaded = datasets[score.dataset]
        values = scores[score.dataset][score.key]
        if values.notna().sum() == 0:
            continue
        # Different reporters sit in different files, so scores meet on the family ID.
        link = loaded.family if loaded.family is not None else loaded.frame[loaded.id_column]
        linked = pd.Series(values.to_numpy(), index=link.to_numpy())
        linked = linked[~linked.index.duplicated() & linked.index.notna()]
        waves.setdefault((loaded.config.study, loaded.config.wave), {})[score.key] = linked
    rows = []
    for (study, wave), series in sorted(waves.items(), key=lambda kv: wave_order(kv[0][1])):
        if len(series) < 2:
            continue
        table = pd.DataFrame(series)
        keys = list(table.columns)
        r_rows, n_rows = [], []
        for a in keys:
            r_row, n_row = [], []
            for b in keys:
                pair = table[[a]].dropna() if a == b else table[[a, b]].dropna()
                n_row.append(len(pair))
                if a == b:
                    r_row.append(1.0)
                elif len(pair) < defaults.MIN_CORRELATION_N:
                    r_row.append(None)
                else:
                    r = pair[a].corr(pair[b])
                    r_row.append(None if pd.isna(r) else float(r))
            r_rows.append(r_row)
            n_rows.append(n_row)
        rows.append(Correlation(study=study, wave=wave, keys=keys, r=r_rows, n=n_rows))
    return rows


def wave_order(wave: str) -> tuple[int, float | str]:
    return (0, float(wave)) if is_number(wave) else (1, wave)


def is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
