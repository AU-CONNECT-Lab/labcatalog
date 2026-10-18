import pandas as pd

from labcatalog.data.scoring import scorable
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import analysis
from labcatalog.stats.analysis import ITEM_PREFIX, STUDY_KEY, item_variable
from labcatalog.stats.invariance import InvarianceModel, dataset_items, factor_sets, with_freed

MEASURE_SEPARATOR = "@"


def measure_choices(
    result: CatalogResult, datasets: list[str], instruments: list[str], labels: dict[str, str]
) -> dict[str, str]:
    # Each instrument and dataset that has a factor model, as instrument@dataset; pooled over
    # studies, instrument@one file of each study.
    names = {i: (inst.abbreviation or inst.name) for i, inst in result.project.instruments.items()}
    found = {}
    for name in datasets:
        for instrument_id in scorable_scores(result, name):
            if instrument_id in instruments and factor_sets(
                result.project.instruments[instrument_id]
            ):
                found[f"{instrument_id}{MEASURE_SEPARATOR}{name}"] = (
                    f"{names[instrument_id]} ({labels[name]})"
                )
    if analysis.pooling(result, datasets):
        return analysis.pooled(result, datasets, found)
    return found


def scorable_scores(result: CatalogResult, dataset: str) -> dict[str, dict]:
    # Instrument id to its scorable scores in one file, by score id.
    loaded = result.datasets[dataset]
    found: dict[str, dict] = {}
    for s in result.catalog.scores_for(dataset):
        if scorable(loaded, s):
            found.setdefault(s.instrument_id, {})[s.score_id] = s
    return found


def group_options(
    result: CatalogResult, sample: analysis.Sample, group_key: str
) -> list[tuple[float, str]]:
    if group_key == STUDY_KEY:
        return analysis.study_options(result, sample)
    return [(float(o.value), o.label) for o in item_variable(result, group_key).response_options]


def group_models(
    result: CatalogResult, sample: analysis.Sample, measure: str, group_key: str
) -> list[InvarianceModel]:
    # One group per answer option, or per study, paired as the sample pairs them; a group needs
    # more people than items for its covariances.
    instrument_id = measure.split(MEASURE_SEPARATOR)[0]
    names = analysis.parts(measure)
    groups = analysis.values(result, sample, group_key)
    across = (
        STUDY_KEY
        if group_key == STUDY_KEY
        else group_key.removeprefix(ITEM_PREFIX).rsplit("@", 1)[0]
    )
    config = result.datasets[names[0]].config
    models = []
    for kind, members in factor_sets(result.project.instruments[instrument_id]):
        factors = {s.id: list(s.items) for s in members}
        frames = [file_items(result, sample, name, instrument_id, factors) for name in names]
        if any(frame is None for frame in frames):
            continue
        items = pd.concat(frames).dropna()
        found = groups.reindex(items.index)
        occasions = {
            label: items[found == value]
            for value, label in group_options(result, sample, group_key)
        }
        enough = len(items.columns) + 1
        left_out = {k: len(v) for k, v in occasions.items() if 0 < len(v) < enough}
        occasions = {k: v for k, v in occasions.items() if len(v) >= enough}
        if len(occasions) >= 2:
            model = InvarianceModel(
                config.study,
                config.reporter,
                instrument_id,
                kind,
                factors,
                occasions,
                across,
                config.wave,
            )
            model.left_out = left_out
            models.append(with_freed(result.project, model))
    return models


def file_items(
    result: CatalogResult,
    sample: analysis.Sample,
    dataset: str,
    instrument_id: str,
    factors: dict[str, list[str]],
) -> pd.DataFrame | None:
    # The factors' reversed items of one file, by the sample's person keys.
    scores = scorable_scores(result, dataset).get(instrument_id, {})
    if not set(factors) <= set(scores):
        return None
    rows = sample.links.rows[dataset]
    items = dataset_items(result.datasets[dataset], scores, factors)
    return items.iloc[rows.to_numpy()].set_axis(rows.index)
