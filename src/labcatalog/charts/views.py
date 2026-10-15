import pandas as pd
import plotly.graph_objects as go

from labcatalog import defaults
from labcatalog.charts import matrices, plots, scatter
from labcatalog.charts.style import SERIES_COLORS, natural_key, wave_color
from labcatalog.config import dataset_by_name, missing_labels_for
from labcatalog.pipeline import CatalogResult
from labcatalog.resolve import ResolvedScore, as_text_dict
from labcatalog.schema import Instrument, Score
from labcatalog.stats import wave_order

# ---- shared lookups ----


def several_studies(result: CatalogResult) -> bool:
    return len(result.project.config.studies) > 1


def wave_name(result: CatalogResult, study: str, wave: str) -> str:
    if several_studies(result):
        return f"{result.project.config.studies[study].label or study} wave {wave}"
    return f"Wave {wave}"


def all_wave_names(result: CatalogResult) -> list[str]:
    return [
        wave_name(result, study, wave)
        for study, config in result.project.config.studies.items()
        for wave in sorted(config.waves, key=wave_order)
    ]


def wave_colors(result: CatalogResult) -> dict[str, str]:
    colors = {}
    for config in result.project.config.studies.values():
        for i, wave in enumerate(sorted(config.waves, key=wave_order)):
            colors.setdefault(wave, wave_color(i))
    return colors


def dataset_order(result: CatalogResult, names: list[str]) -> list[str]:
    config = result.project.config
    studies = list(config.studies)

    def key(name: str) -> tuple:
        d = dataset_by_name(config, name)
        return (studies.index(d.study), wave_order(d.wave), d.reporter)

    return sorted(dict.fromkeys(names), key=key)


def series_names(result: CatalogResult, names: list[str]) -> dict[str, str]:
    config = result.project.config
    plain = {
        n: wave_name(result, dataset_by_name(config, n).study, dataset_by_name(config, n).wave)
        for n in names
    }
    repeated = {label for label in plain.values() if list(plain.values()).count(label) > 1}
    return {
        n: f"{label} · {dataset_by_name(config, n).reporter}" if label in repeated else label
        for n, label in plain.items()
    }


def series_color(result: CatalogResult, name: str) -> str:
    return wave_colors(result)[dataset_by_name(result.project.config, name).wave]


def instrument_datasets(result: CatalogResult, instrument_id: str) -> list[str]:
    names = [v.dataset for v in result.catalog.variables if v.instrument_id == instrument_id]
    return dataset_order(result, names)


def is_total(instrument: Instrument, score: Score) -> bool:
    # The total is the score that covers every item the instrument's scores use.
    used = set().union(*(set(s.items) for s in instrument.scores))
    return set(score.items) == used


def total_score(instrument: Instrument) -> Score | None:
    return next((s for s in instrument.scores if is_total(instrument, s)), None)


def resolved(result: CatalogResult, instrument_id: str, score_id: str) -> list[ResolvedScore]:
    found = [
        s
        for s in result.catalog.scores
        if (s.instrument_id, s.score_id) == (instrument_id, score_id)
    ]
    order = dataset_order(result, [s.dataset for s in found])
    return sorted(found, key=lambda s: order.index(s.dataset))


def summary_of(result: CatalogResult, key: str):
    return next(s for s in result.summary.scores if s.key == key)


def item_text(instrument: Instrument, item_id: str) -> str:
    item = next(i for i in instrument.items if i.id == item_id)
    text = " / ".join(as_text_dict(item.text).values())
    return f"{text} (R)" if item.reverse else text


def short_label(instrument: Instrument, score: Score) -> str:
    return f"{instrument.abbreviation or instrument.id} {score.label.lower()}"


def option_range(instrument: Instrument) -> tuple[float, float]:
    values = [float(o.value) for r in instrument.response_sets for o in r.options]
    return min(values), max(values)


def ids_of(result: CatalogResult, dataset: str) -> pd.Series:
    loaded = result.datasets[dataset]
    return loaded.frame[loaded.id_column].astype(str)


# ---- instrument page ----


def score_boxes(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    instrument = result.project.instruments[instrument_id]
    if not instrument.scores:
        return None
    series = []
    for name in instrument_datasets(result, instrument_id):
        values = {}
        for i, score in enumerate(instrument.scores):
            key = next(
                (
                    s.key
                    for s in result.catalog.scores_for(name)
                    if s.score_id == score.id and s.instrument_id == instrument_id
                ),
                None,
            )
            if key is not None:
                values[i] = (
                    result.scores[name][key].to_numpy(dtype=float),
                    ids_of(result, name).tolist(),
                )
        if values:
            series.append(
                {
                    "name": series_names(result, [name])[name],
                    "color": series_color(result, name),
                    "values": values,
                }
            )
    title = f"{instrument.abbreviation or instrument.id} scores by wave"
    return (
        plots.score_boxes(title, [s.label for s in instrument.scores], series) if series else None
    )


def score_distribution(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    instrument = result.project.instruments[instrument_id]
    total = total_score(instrument)
    if total is None:
        return None
    scores = [
        s for s in resolved(result, instrument_id, total.id) if summary_of(result, s.key).n_valid
    ]
    names = series_names(result, [s.dataset for s in scores])
    rows = [
        {
            "label": names[s.dataset],
            "color": series_color(result, s.dataset),
            "n": summary_of(result, s.key).n_valid,
            "mean": summary_of(result, s.key).mean,
            "histogram": summary_of(result, s.key).histogram,
            "possible_range": summary_of(result, s.key).possible_range,
        }
        for s in scores
    ]
    return (
        plots.score_ridges(short_label(instrument, total), rows, integer=total.method == "sum")
        if rows
        else None
    )


def item_responses(result: CatalogResult, instrument_id: str) -> list[go.Figure]:
    instrument = result.project.instruments[instrument_id]
    default = instrument.default_response_set or instrument.response_sets[0].id
    names = series_names(result, instrument_datasets(result, instrument_id))
    counts = {(v.dataset, v.column): v.value_counts for v in result.summary.variables}
    figures = []
    for response_set in instrument.response_sets:
        rows = []
        for item in instrument.items:
            if (item.response_set or default) != response_set.id:
                continue
            for v in result.catalog.variables:
                if (
                    v.instrument_id == instrument_id
                    and v.item_id == item.id
                    and (v.dataset, v.column) in counts
                ):
                    rows.append(
                        {
                            "label": f"{item.id} · {names[v.dataset]}",
                            "text": item_text(instrument, item.id),
                            "counts": counts[(v.dataset, v.column)],
                            "order": (instrument.items.index(item), list(names).index(v.dataset)),
                        }
                    )
        if rows:
            rows.sort(key=lambda r: r["order"])
            options = [(str(o.value), o.label) for o in response_set.options]
            figures.append(plots.response_bars(options, rows))
    return figures


def item_total(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    instrument = result.project.instruments[instrument_id]
    total = total_score(instrument)
    if total is None:
        return None
    items = {
        v.column: v.item_id for v in result.catalog.variables if v.instrument_id == instrument_id
    }
    scores = [
        s for s in resolved(result, instrument_id, total.id) if summary_of(result, s.key).item_total
    ]
    names = series_names(result, [s.dataset for s in scores])
    series = []
    for s in scores:
        summary = summary_of(result, s.key)
        alpha = f" (α {summary.alpha:.2f})" if summary.alpha is not None else ""
        series.append(
            {
                "name": names[s.dataset] + alpha,
                "color": series_color(result, s.dataset),
                "values": {items[t.column]: t.r for t in summary.item_total},
            }
        )
    if not series:
        return None
    members = [
        {"id": i, "tick": i, "hover": f"{i}: {item_text(instrument, i)}"} for i in total.items
    ]
    title = f"{short_label(instrument, total)}: item-total correlation"
    return plots.paired_strip([("", members)], series, "Corrected item-total r", title)


def item_profile(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    instrument = result.project.instruments[instrument_id]
    if len(instrument.items) < 3:
        return None
    means = {(v.dataset, v.column): v.mean for v in result.summary.variables}
    names = series_names(result, instrument_datasets(result, instrument_id))
    series = []
    for name, label in names.items():
        values = {
            v.item_id: means.get((name, v.column))
            for v in result.catalog.variables_for(name)
            if v.instrument_id == instrument_id
        }
        if any(value is not None for value in values.values()):
            series.append({"name": label, "color": series_color(result, name), "values": values})
    axes = [i.id for i in instrument.items]
    hovers = [f"{i.id}: {item_text(instrument, i.id)}" for i in instrument.items]
    return plots.profile_radar(axes, hovers, series, option_range(instrument)) if series else None


def subscale_profile(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    # Subscales are put on the answer scale (mean per item) so subscales of different lengths compare.
    instrument = result.project.instruments[instrument_id]
    subscales = [s for s in instrument.scores if not is_total(instrument, s)]
    if len(subscales) < 3:
        return None
    names = series_names(result, instrument_datasets(result, instrument_id))
    series = []
    for name, label in names.items():
        values = {}
        for score in subscales:
            key = next(
                (s.key for s in result.catalog.scores_for(name) if s.score_id == score.id), None
            )
            mean = summary_of(result, key).mean if key else None
            if mean is not None:
                values[score.label] = mean / len(score.items) if score.method == "sum" else mean
        if values:
            series.append({"name": label, "color": series_color(result, name), "values": values})
    axes = [s.label for s in subscales]
    hovers = [f"{s.label} ({len(s.items)} items)" for s in subscales]
    return plots.profile_radar(axes, hovers, series, option_range(instrument)) if series else None


def item_correlations(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    instrument = result.project.instruments[instrument_id]
    total = total_score(instrument)
    if total is None:
        return None
    items = {
        v.column: v.item_id for v in result.catalog.variables if v.instrument_id == instrument_id
    }
    scores = [
        s
        for s in resolved(result, instrument_id, total.id)
        if summary_of(result, s.key).item_correlations
    ]
    names = series_names(result, [s.dataset for s in scores])
    panels = [
        {
            "title": names[s.dataset],
            "labels": [items[c] for c in summary_of(result, s.key).item_columns],
            "r": summary_of(result, s.key).item_correlations,
        }
        for s in scores
    ]
    return matrices.item_correlations(panels, "Spearman ρ") if panels else None


def score_means(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    config = result.project.config
    instrument = result.project.instruments[instrument_id]
    retained = {
        (r.study, r.reporter, r.score_id, r.wave): r
        for r in result.summary.retained
        if r.instrument_id == instrument_id
    }
    panels = []
    for score in instrument.scores:
        by_reporter: dict[tuple[str, str], list[ResolvedScore]] = {}
        for s in resolved(result, instrument_id, score.id):
            d = dataset_by_name(config, s.dataset)
            by_reporter.setdefault((d.study, d.reporter), []).append(s)
        for (study, reporter), scores in by_reporter.items():
            if len(scores) < 2:
                continue
            everyone, kept = [], []
            for s in scores:
                wave = dataset_by_name(config, s.dataset).wave
                summary = summary_of(result, s.key)
                if summary.mean is not None:
                    everyone.append((wave_name(result, study, wave), summary.mean, summary.n_valid))
                r = retained.get((study, reporter, score.id, wave))
                if r is not None and r.mean is not None:
                    kept.append((wave_name(result, study, wave), r.mean, r.n))
            panels.append(
                {
                    "title": score.label
                    if len(by_reporter) == 1
                    else f"{score.label} ({reporter})",
                    "series": [
                        {"name": "All participants", "color": SERIES_COLORS[0], "points": everyone},
                        {"name": "In every wave", "color": SERIES_COLORS[1], "points": kept},
                    ],
                }
            )
    return plots.score_means(panels, all_wave_names(result)) if panels else None


def stability(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    rows = [r for r in result.summary.stability if r.instrument_id == instrument_id]
    if not rows:
        return None
    instrument = result.project.instruments[instrument_id]
    reporters = list(dict.fromkeys(r.reporter for r in rows))
    members = [
        {
            "id": (score.id, reporter),
            "tick": score.label if len(reporters) == 1 else f"{score.label} ({reporter})",
            "hover": f"{short_label(instrument, score)}, {reporter}",
        }
        for score in instrument.scores
        for reporter in reporters
        if any(r.score_id == score.id and r.reporter == reporter for r in rows)
    ]
    pairs = list(dict.fromkeys((r.study, r.from_wave, r.to_wave) for r in rows))
    series = [
        {
            "name": f"{wave_name(result, study, a)} → {wave_name(result, study, b)}",
            "color": wave_colors(result)[b],
            "values": {
                (r.score_id, r.reporter): r.r
                for r in rows
                if (r.study, r.from_wave, r.to_wave) == (study, a, b)
            },
        }
        for study, a, b in pairs
    ]
    return plots.paired_strip(
        [("", members)], series, "r with one wave earlier", "Stability across waves (same person)"
    )


def score_correlates(result: CatalogResult, instrument_id: str, score_id: str) -> go.Figure | None:
    # This score against every other score measured in the same wave, strongest first.
    config = result.project.config
    by_key = {s.key: s for s in result.catalog.scores}
    reporter = {s.key: dataset_by_name(config, s.dataset).reporter for s in result.catalog.scores}
    reporters_of: dict[str, set[str]] = {}
    for s in result.catalog.scores:
        reporters_of.setdefault(s.instrument_id, set()).add(reporter[s.key])
    own = {s.key for s in resolved(result, instrument_id, score_id)}
    several_own = len({reporter[k] for k in own}) > 1
    members: dict[tuple[str, str, str], dict] = {}
    series = []
    for corr in result.summary.correlations:
        for i, key in enumerate(corr.keys):
            if key not in own:
                continue
            values = {}
            for j, other_key in enumerate(corr.keys):
                other = by_key[other_key]
                if j == i or corr.r[i][j] is None or nested(result, by_key[key], other):
                    continue
                member = (other.instrument_id, other.score_id, reporter[other_key])
                values[member] = corr.r[i][j]
                if member not in members:
                    other_instrument = result.project.instruments[other.instrument_id]
                    label = short_label(other_instrument, definition(result, other))
                    several = len(reporters_of[other.instrument_id]) > 1
                    members[member] = {
                        "id": member,
                        "tick": f"{label} ({member[2]})" if several else label,
                        "hover": f"{label}, {member[2]}",
                    }
            name = wave_name(result, corr.study, corr.wave)
            series.append(
                {
                    "name": f"{name} · {reporter[key]}" if several_own else name,
                    "color": series_color(result, by_key[key].dataset),
                    "values": values,
                }
            )
    if not members:
        return None

    def strength(member: tuple) -> float:
        found = [abs(s["values"][member]) for s in series if member in s["values"]]
        return sum(found) / len(found)

    ordered = sorted(members, key=strength, reverse=True)
    instrument = result.project.instruments[instrument_id]
    score = next(s for s in instrument.scores if s.id == score_id)
    return plots.paired_strip(
        [("", [members[m] for m in ordered])],
        series,
        "Pearson r",
        f"{short_label(instrument, score)} against every other score",
    )


def nested(result: CatalogResult, a: ResolvedScore, b: ResolvedScore) -> bool:
    # A score and its own subscale in one file share items, so their r says nothing new.
    if a.dataset != b.dataset or a.instrument_id != b.instrument_id:
        return False
    items_a, items_b = set(definition(result, a).items), set(definition(result, b).items)
    return items_a >= items_b or items_b >= items_a


def definition(result: CatalogResult, score: ResolvedScore) -> Score:
    instrument = result.project.instruments[score.instrument_id]
    return next(s for s in instrument.scores if s.id == score.score_id)


def instrument_choices(result: CatalogResult, instrument_id: str) -> dict[str, str]:
    return {
        choice: label
        for choice, label in score_choices(result).items()
        if choice.split("|")[0] == instrument_id
    }


def default_score(result: CatalogResult, instrument_id: str) -> str:
    total = total_score(result.project.instruments[instrument_id])
    choices = list(instrument_choices(result, instrument_id))
    preferred = f"{instrument_id}|{total.id}" if total else None
    return preferred if preferred in choices else choices[0]


def default_partner(result: CatalogResult, choice: str) -> str:
    # A total from another instrument that meets this score in some wave; its own subscales say little.
    met = partners(result, choice)
    others = [c for c in met if c.split("|")[0] != choice.split("|")[0]]
    totals = []
    for other in others:
        instrument_id, score_id = other.split("|")
        instrument = result.project.instruments[instrument_id]
        if is_total(instrument, next(s for s in instrument.scores if s.id == score_id)):
            totals.append(other)
    rest = [c for c in score_choices(result) if c != choice]
    return (totals or others or rest)[0]


def partners(result: CatalogResult, choice: str) -> list[str]:
    by_key = {s.key: f"{s.instrument_id}|{s.score_id}" for s in result.catalog.scores}
    met = []
    for corr in result.summary.correlations:
        for i, key in enumerate(corr.keys):
            if by_key[key] == choice:
                met += [by_key[k] for j, k in enumerate(corr.keys) if corr.r[i][j] is not None]
    order = list(score_choices(result))
    return sorted(set(met) - {choice}, key=order.index)


# ---- overview page ----


def collection_pace(result: CatalogResult) -> go.Figure | None:
    config = result.project.config
    by_reporter: dict[str, dict[str, list[int]]] = {}
    colors = {}
    for summary in result.summary.datasets:
        if not summary.collected_by_day:
            continue
        d = dataset_by_name(config, summary.dataset)
        days = {pd.Timestamp(day): n for day, n in summary.collected_by_day.items()}
        start = config.studies[d.study].waves[d.wave].start
        start = pd.Timestamp(start) if start else min(days)
        name = wave_name(result, d.study, d.wave)
        colors[name] = wave_colors(result)[d.wave]
        offsets = by_reporter.setdefault(d.reporter, {}).setdefault(name, [])
        for day, n in days.items():
            offsets += [(day - start).days] * n
    if not by_reporter:
        return None
    facets = [
        {"title": r.capitalize(), "unit": "rows", "days": days} for r, days in by_reporter.items()
    ]
    waves = [w for w in all_wave_names(result) if w in colors]
    return plots.collection_pace(facets, waves, colors)


# ---- scores against each other ----


def correlation_waves(result: CatalogResult) -> list[tuple[str, str]]:
    return [(c.study, c.wave) for c in result.summary.correlations if len(c.keys) > 1]


def instrument_order(result: CatalogResult) -> list[str]:
    return list(result.project.instruments)


def correlated_instruments(result: CatalogResult) -> dict[str, str]:
    keys = {key for c in result.summary.correlations for key in c.keys}
    found = {s.instrument_id for s in result.catalog.scores if s.key in keys}
    return {
        i: result.project.instruments[i].abbreviation or i
        for i in instrument_order(result)
        if i in found
    }


def score_panel(
    result: CatalogResult, study: str, wave: str, instruments: list[str]
) -> dict | None:
    corr = next(c for c in result.summary.correlations if (c.study, c.wave) == (study, wave))
    by_key = {s.key: s for s in result.catalog.scores}
    order = instrument_order(result)

    def rank(i: int) -> tuple:
        s = by_key[corr.keys[i]]
        instrument = result.project.instruments[s.instrument_id]
        score = definition(result, s)
        return (
            order.index(s.instrument_id),
            not is_total(instrument, score),
            instrument.scores.index(score),
        )

    picked = [i for i, key in enumerate(corr.keys) if by_key[key].instrument_id in instruments]
    if len(picked) < 2:
        return None
    idx = sorted(picked, key=rank)
    resolved_scores = [by_key[corr.keys[i]] for i in idx]
    definitions = [definition(result, s) for s in resolved_scores]
    skip = {
        (a, b)
        for a in range(len(idx))
        for b in range(a + 1, len(idx))
        if nested(result, resolved_scores[a], resolved_scores[b])
    }
    return {
        "title": wave_name(result, study, wave),
        "r": [[corr.r[i][j] for j in idx] for i in idx],
        "n": [[corr.n[i][j] for j in idx] for i in idx],
        "labels": [
            short_label(result.project.instruments[s.instrument_id], d)
            for s, d in zip(resolved_scores, definitions, strict=True)
        ],
        "short": [d.label for d in definitions],
        "groups": [s.instrument_id for s in resolved_scores],
        "skip": skip,
    }


def score_circle(
    result: CatalogResult, study: str, wave: str, instruments: list[str]
) -> go.Figure | None:
    p = score_panel(result, study, wave, instruments)
    if p is None:
        return None
    return matrices.score_circle(
        p["r"],
        p["n"],
        p["labels"],
        p["groups"],
        instrument_order(result),
        instrument_labels(result),
        p["skip"],
        defaults.CHART_MIN_R,
    )


def score_matrices(result: CatalogResult, instruments: list[str]) -> go.Figure | None:
    panels = [
        p
        for study, wave in correlation_waves(result)
        if (p := score_panel(result, study, wave, instruments)) is not None
    ]
    if not panels:
        return None
    return matrices.score_matrices(panels, instrument_order(result), instrument_labels(result))


def instrument_labels(result: CatalogResult) -> dict[str, str]:
    return {i: x.abbreviation or i for i, x in result.project.instruments.items()}


def score_choices(result: CatalogResult) -> dict[str, str]:
    seen = {(s.instrument_id, s.score_id): s for s in result.catalog.scores}
    return {
        f"{instrument_id}|{score_id}": short_label(
            result.project.instruments[instrument_id], definition(result, s)
        )
        for (instrument_id, score_id), s in seen.items()
    }


def linked(result: CatalogResult, score: ResolvedScore) -> pd.Series:
    # People meet across datasets the way stats.correlate_by says; repeated keys are ambiguous.
    loaded = result.datasets[score.dataset]
    by_group = (
        result.project.config.stats.correlate_by not in ("id", "none") and loaded.group is not None
    )
    keys = loaded.group if by_group else loaded.frame[loaded.id_column]
    values = pd.Series(
        result.scores[score.dataset][score.key].to_numpy(), index=keys.astype(str).to_numpy()
    ).dropna()
    return values[~values.index.duplicated(keep=False)]


def regression(result: CatalogResult, x_choice: str, y_choice: str) -> go.Figure | None:
    x_id, y_id = x_choice.split("|"), y_choice.split("|")
    config = result.project.config
    groups = []
    for study, study_config in config.studies.items():
        for wave in sorted(study_config.waves, key=wave_order):
            xs = [
                s
                for s in resolved(result, *x_id)
                if (
                    dataset_by_name(config, s.dataset).study,
                    dataset_by_name(config, s.dataset).wave,
                )
                == (study, wave)
            ]
            ys = [
                s
                for s in resolved(result, *y_id)
                if (
                    dataset_by_name(config, s.dataset).study,
                    dataset_by_name(config, s.dataset).wave,
                )
                == (study, wave)
            ]
            if not xs or not ys:
                continue
            same = [(x, y) for x in xs for y in ys if x.dataset == y.dataset]
            if same:
                x, y = same[0]
                frame = pd.DataFrame(
                    {
                        "x": result.scores[x.dataset][x.key],
                        "y": result.scores[y.dataset][y.key],
                        "id": ids_of(result, x.dataset),
                    }
                ).dropna()
                frame = frame.set_index("id")
            else:
                frame = pd.concat(
                    [linked(result, xs[0]).rename("x"), linked(result, ys[0]).rename("y")],
                    axis=1,
                    join="inner",
                ).dropna()
            if len(frame) < defaults.MIN_CORRELATION_N:
                continue
            groups.append(
                {
                    "name": wave_name(result, study, wave),
                    "color": wave_colors(result)[wave],
                    "x": frame["x"].to_numpy(dtype=float),
                    "y": frame["y"].to_numpy(dtype=float),
                    "ids": [str(i) for i in frame.index],
                }
            )
    if not groups:
        return None
    choices = score_choices(result)
    return scatter.regression(choices[x_choice], choices[y_choice], groups)


# ---- one instrument in one dataset ----


def people(result: CatalogResult, dataset: str) -> list[str]:
    # A repeated ID gets a row number so each row stays its own column.
    seen: dict[str, int] = {}
    shown = []
    for pid in ids_of(result, dataset):
        seen[pid] = seen.get(pid, 0) + 1
        shown.append(pid if seen[pid] == 1 else f"{pid} (row {seen[pid]})")
    return shown


def page_count(result: CatalogResult, dataset: str) -> int:
    return max(1, -(-len(result.datasets[dataset].frame) // defaults.CHART_PEOPLE_PER_PAGE))


def page_rows(result: CatalogResult, dataset: str, page: int) -> tuple[list[int], list[str]]:
    shown = people(result, dataset)
    order = sorted(range(len(shown)), key=lambda i: natural_key(shown[i]))
    size = defaults.CHART_PEOPLE_PER_PAGE
    rows = order[(page - 1) * size : page * size]
    return rows, [shown[i] for i in rows]


def answer_status(
    result: CatalogResult, dataset: str, column: str, options: list
) -> tuple[pd.Series, pd.Series]:
    loaded = result.datasets[dataset]
    codes = missing_labels_for(result.project.config, loaded.config)
    text = loaded.frame[column].fillna("").astype(str).str.strip()
    numbers = loaded.numbers(column)
    option_values = {float(o.value): o.label for o in options}
    code_numbers = {}
    for code, label in codes.items():
        try:
            code_numbers[float(code)] = label
        except ValueError:
            pass
    status = pd.Series("unexpected", index=text.index)
    label = text + " is not an option"
    is_code = text.isin([c for c in codes if c]) | numbers.isin(list(code_numbers))
    status[is_code] = "missing"
    label[is_code] = (
        text[is_code].map(lambda t: codes.get(t) or code_numbers.get(float(t), t))
        + " ("
        + text[is_code]
        + ")"
    )
    is_option = numbers.isin(list(option_values))
    status[is_option] = "valid"
    label[is_option] = numbers[is_option].map(option_values) + " (" + text[is_option] + ")"
    blank = text == ""
    status[blank] = "blank"
    label[blank] = "blank"
    return status, label


def answer_grid(
    result: CatalogResult, dataset: str, page: int, instrument_id: str
) -> go.Figure | None:
    variables = [
        v
        for v in result.catalog.variables_for(dataset)
        if v.instrument_id == instrument_id and v.column in result.datasets[dataset].frame
    ]
    if not variables:
        return None
    rows, shown = page_rows(result, dataset, page)
    cells, labels = [], {}
    for v in variables:
        status, label = answer_status(result, dataset, v.column, v.response_options)
        labels[v.column] = f"{v.column}: {next(iter(v.text.values()), '')[:60]}"
        for row, person in zip(rows, shown, strict=True):
            cells.append(
                {
                    "person": person,
                    "item": v.column,
                    "status": status.iloc[row],
                    "text": label.iloc[row],
                }
            )
    return matrices.answer_grid(cells, labels)


def standardized_scores(
    result: CatalogResult, dataset: str, page: int, instrument_id: str
) -> go.Figure | None:
    scores = [s for s in result.catalog.scores_for(dataset) if s.instrument_id == instrument_id]
    if not scores:
        return None
    instrument = result.project.instruments[instrument_id]
    rows, shown = page_rows(result, dataset, page)
    points = []
    for s in scores:
        values = result.scores[dataset][s.key]
        if values.notna().sum() < defaults.MIN_CORRELATION_N or not values.std():
            continue
        z = (values - values.mean()) / values.std()
        for row, person in zip(rows, shown, strict=True):
            if pd.notna(z.iloc[row]):
                points.append(
                    {
                        "id": person,
                        "variable": short_label(instrument, definition(result, s)),
                        "z": float(z.iloc[row]),
                        "value": float(values.iloc[row]),
                    }
                )
    return scatter.standardized(points) if points else None


# ---- small multiples ----


def wave_profiles(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    # One panel per wave: that wave's item means in colour, the other waves faint behind it.
    instrument = result.project.instruments[instrument_id]
    means = {(v.dataset, v.column): v.mean for v in result.summary.variables}
    names = series_names(result, instrument_datasets(result, instrument_id))
    items = [i.id for i in instrument.items]
    lines = {}
    for name in names:
        by_item = {
            v.item_id: means.get((name, v.column))
            for v in result.catalog.variables_for(name)
            if v.instrument_id == instrument_id
        }
        lines[name] = [by_item.get(i) for i in items]
    if len(lines) < 2:
        return None
    hovers = [f"{i}: {item_text(instrument, i)}" for i in items]
    panels = [
        {
            "title": names[name],
            "x": items,
            "hover": hovers,
            "background": [values for other, values in lines.items() if other != name],
            "highlight": {
                "name": names[name],
                "color": series_color(result, name),
                "values": values,
            },
        }
        for name, values in lines.items()
    ]
    return plots.small_multiples(panels, option_range(instrument), "Mean answer")


def people_profiles(result: CatalogResult, instrument_id: str, dataset: str) -> go.Figure | None:
    # One panel per subscale: every person's answers faint, the mean of everyone in colour.
    instrument = result.project.instruments[instrument_id]
    columns = {
        v.item_id: v
        for v in result.catalog.variables_for(dataset)
        if v.instrument_id == instrument_id and v.column in result.datasets[dataset].frame
    }
    if not columns:
        return None
    subscales = [s for s in instrument.scores if not is_total(instrument, s)]
    groups = [(s.label, s.items) for s in subscales] or [
        ("All items", [i.id for i in instrument.items])
    ]
    loaded = result.datasets[dataset]
    rows = len(loaded.frame)
    step = max(1, -(-rows // defaults.CHART_PEOPLE_PER_PAGE))
    shown = list(range(0, rows, step))
    color = series_color(result, dataset)
    panels = []
    for title, item_ids in groups:
        item_ids = [i for i in item_ids if i in columns]
        if not item_ids:
            continue
        answers = pd.DataFrame(
            {
                i: loaded.numbers(columns[i].column).where(
                    loaded.numbers(columns[i].column).isin(
                        [float(o.value) for o in columns[i].response_options]
                    )
                )
                for i in item_ids
            }
        )
        panels.append(
            {
                "title": title if step == 1 else f"{title} ({len(shown)} of {rows} people)",
                "x": item_ids,
                "hover": [f"{i}: {item_text(instrument, i)}" for i in item_ids],
                "background": answers.iloc[shown].to_numpy(dtype=float).tolist(),
                "highlight": {"name": "Mean", "color": color, "values": answers.mean().tolist()},
            }
        )
    return plots.small_multiples(panels, option_range(instrument), "Answer") if panels else None
