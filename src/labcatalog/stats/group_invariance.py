from labcatalog.data.scoring import scorable
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import analysis
from labcatalog.stats.analysis import ITEM_PREFIX, item_variable
from labcatalog.stats.invariance import InvarianceModel, dataset_items, factor_sets, with_freed

MEASURE_SEPARATOR = "@"


def measure_choices(
    result: CatalogResult, datasets: list[str], instruments: list[str], labels: dict[str, str]
) -> dict[str, str]:
    # Each instrument and dataset that has a factor model, as instrument@dataset.
    names = {i: (inst.abbreviation or inst.name) for i, inst in result.project.instruments.items()}
    found = {}
    for name in datasets:
        loaded = result.datasets[name]
        scored = {
            s.instrument_id: s for s in result.catalog.scores_for(name) if scorable(loaded, s)
        }
        for instrument_id in scored:
            if instrument_id in instruments and factor_sets(
                result.project.instruments[instrument_id]
            ):
                found[f"{instrument_id}{MEASURE_SEPARATOR}{name}"] = (
                    f"{names[instrument_id]} ({labels[name]})"
                )
    return found


def group_models(
    result: CatalogResult, sample: analysis.Sample, measure: str, group_key: str
) -> list[InvarianceModel]:
    # One group per answer option, paired as the sample pairs them; a group needs more people than
    # items for its covariances.
    instrument_id, dataset = measure.split(MEASURE_SEPARATOR)
    loaded = result.datasets[dataset]
    scores = {
        s.score_id: s
        for s in result.catalog.scores_for(dataset)
        if s.instrument_id == instrument_id and scorable(loaded, s)
    }
    variable = item_variable(result, group_key)
    groups = analysis.values(result, sample, group_key)
    rows = sample.links.rows[dataset]
    across = group_key.removeprefix(ITEM_PREFIX).rsplit("@", 1)[0]
    config = loaded.config
    models = []
    for kind, members in factor_sets(result.project.instruments[instrument_id]):
        factors = {s.id: list(s.items) for s in members}
        if not set(factors) <= set(scores):
            continue
        items = dataset_items(loaded, scores, factors).iloc[rows.to_numpy()].set_axis(rows.index)
        items = items.dropna()
        found = groups.reindex(items.index)
        occasions = {
            option.label: items[found == float(option.value)]
            for option in variable.response_options
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
