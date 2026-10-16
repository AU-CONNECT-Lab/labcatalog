from collections import Counter
from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

from labcatalog import defaults
from labcatalog.charts import matrices, network, plots, scatter
from labcatalog.charts.style import group_color, natural_key, pair_color, wave_color
from labcatalog.config import dataset_by_name, missing_labels_for
from labcatalog.data.resolve import ResolvedScore, as_text_dict
from labcatalog.metadata.browse import as_set, facet_label, facet_names, value_order
from labcatalog.pipeline import CatalogResult
from labcatalog.schema import Instrument, Score
from labcatalog.stats import analysis
from labcatalog.stats.summary import wave_order

RADAR_AXES = 3
# Room beyond 0% and 100% so dots at either end stay whole.
LEVEL_RANGE = (-0.03, 1.03)

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
    default = instrument.default_response_set
    names = series_names(result, instrument_datasets(result, instrument_id))
    counts = {(v.dataset, v.column): v.value_counts for v in result.summary.variables}
    figures = []
    for response_set in instrument.response_sets:
        rows = []
        for item in instrument.items:
            if item.type != "choice" or (item.response_set or default) != response_set.id:
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


def subscale_radars(result: CatalogResult, instrument_id: str) -> go.Figure | None:
    # The subscales side by side first, then each subscale's items; every wave on each.
    instrument = result.project.instruments[instrument_id]
    subscales = subscales_of(instrument)
    names = series_names(result, instrument_datasets(result, instrument_id))
    panels = []
    if len(subscales) >= RADAR_AXES:
        found = subscale_item_means(result, instrument_id)
        panels.append(
            radar_panel(
                result,
                names,
                "Subscales",
                [s.label for s in subscales],
                [f"{s.label}: mean item score, {len(s.items)} items" for s in subscales],
                lambda name: {s.label: found.get((s.id, name)) for s in subscales},
            )
        )
    groups = [(s.label, list(s.items)) for s in subscales if len(s.items) >= RADAR_AXES]
    if not groups:
        groups = [("All items", [i.id for i in instrument.items if i.type == "choice"])]
    means = {(v.dataset, v.column): v.mean for v in result.summary.variables}
    for title, items in groups:
        if len(items) < RADAR_AXES:
            continue
        panels.append(
            radar_panel(
                result,
                names,
                title,
                items,
                [f"{i}: {item_text(instrument, i)}" for i in items],
                lambda name, items=items: {
                    v.item_id: means.get((name, v.column))
                    for v in result.catalog.variables_for(name)
                    if v.instrument_id == instrument_id and v.item_id in items
                },
            )
        )
    panels = [p for p in panels if p is not None]
    return plots.radar_grid(panels, option_range(instrument)) if panels else None


def radar_panel(
    result: CatalogResult,
    names: dict[str, str],
    title: str,
    axes: list[str],
    hovers: list[str],
    values_of: Callable[[str], dict[str, float | None]],
) -> dict | None:
    series = []
    for name, label in names.items():
        values = values_of(name)
        if any(value is not None for value in values.values()):
            series.append({"name": label, "color": series_color(result, name), "values": values})
    return {"title": title, "axes": axes, "hovers": hovers, "series": series} if series else None


def subscale_item_means(result: CatalogResult, instrument_id: str) -> dict[tuple[str, str], float]:
    # A sum score divided by its item count, so subscales of different lengths share the option scale.
    instrument = result.project.instruments[instrument_id]
    per_item = {s.id: len(s.items) if s.method == "sum" else 1 for s in subscales_of(instrument)}
    found = {}
    for score in result.catalog.scores:
        if score.instrument_id == instrument_id and score.score_id in per_item:
            mean = summary_of(result, score.key).mean
            if mean is not None:
                found[(score.score_id, score.dataset)] = mean / per_item[score.score_id]
    return found


def short_subscales(result: CatalogResult, instrument_id: str) -> list[str]:
    instrument = result.project.instruments[instrument_id]
    return [s.label for s in subscales_of(instrument) if len(s.items) < RADAR_AXES]


def radar_note(result: CatalogResult, instrument_id: str) -> str:
    short = short_subscales(result, instrument_id)
    if not short:
        return ""
    if len(short) == len(subscales_of(result.project.instruments[instrument_id])):
        return f"{', '.join(short)}: too few items each for a radar, so all items share one."
    return f"No radar for {', '.join(short)}: a radar needs at least three items."


def subscales_of(instrument: Instrument) -> list[Score]:
    return [s for s in instrument.scores if not is_total(instrument, s)]


def item_waves(result: CatalogResult, instrument_id: str) -> dict[str, str]:
    # Datasets whose total score has item correlations, named the way the other charts name waves.
    total = total_score(result.project.instruments[instrument_id])
    if total is None:
        return {}
    found = [
        s.dataset
        for s in resolved(result, instrument_id, total.id)
        if summary_of(result, s.key).item_correlations
    ]
    return series_names(result, found)


def item_correlations(
    result: CatalogResult, instrument_id: str, dataset: str
) -> tuple[list[str], np.ndarray, int]:
    # Items in the instrument's own order, with the n of people who answered them all.
    total = total_score(result.project.instruments[instrument_id])
    score = next(s for s in resolved(result, instrument_id, total.id) if s.dataset == dataset)
    summary = summary_of(result, score.key)
    columns = {
        v.item_id: v.column
        for v in result.catalog.variables_for(dataset)
        if v.instrument_id == instrument_id
    }
    where = {c: i for i, c in enumerate(summary.item_columns)}
    items = [
        i.id for i in result.project.instruments[instrument_id].items if columns.get(i.id) in where
    ]
    rows = [where[columns[item]] for item in items]
    z = matrices.as_matrix([[summary.item_correlations[a][b] for b in rows] for a in rows])
    return items, z, summary.n_complete


def item_grid(result: CatalogResult, instrument_id: str, dataset: str) -> go.Figure | None:
    items, z, n = item_correlations(result, instrument_id, dataset)
    hover = [
        [f"{a} × {b}<br>ρ = {z[i, j]:.2f}, n = {n}" for j, b in enumerate(items)]
        for i, a in enumerate(items)
    ]
    return matrices.heatmap(z, items, hover, "Spearman ρ")


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
                        {"name": "All participants", "color": pair_color(0), "points": everyone},
                        {"name": "In every wave", "color": pair_color(1), "points": kept},
                    ],
                }
            )
    return plots.score_means(panels, all_wave_names(result)) if panels else None


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
    return plots.dot_rows(
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


# ---- overview page ----


def timeline(result: CatalogResult, today: date | None = None) -> go.Figure | None:
    # Each wave from its start to its end with its counts; milestones on their own lane.
    config = result.project.config
    today = today or date.today()
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for r in result.summary.retention:
        counts.setdefault((r.study, r.wave), {})[r.reporter] = r.n
    lanes, bars, marks = [], [], []
    for study, study_config in config.studies.items():
        earlier = None
        for wave in sorted(study_config.waves, key=wave_order):
            dates = study_config.waves[wave]
            if dates.start is None:
                continue
            lane = wave_name(result, study, wave)
            found = counts.get((study, wave), {})
            ongoing = dates.end is None
            bar = {
                "lane": lane,
                "start": dates.start,
                "end": dates.end or today,
                "ongoing": ongoing,
                "color": wave_colors(result)[wave],
                "hover": f"<b>{lane}</b><br>{dates.start} to {dates.end or 'now, still collecting'}"
                + "".join(f"<br>{reporter}: {n}" for reporter, n in found.items()),
            }
            before = counts.get((study, earlier), {}) if earlier else {}
            bar["text"] = ", ".join(
                f"{reporter} {n}"
                + (
                    f" of {before[reporter]} ({n / before[reporter]:.0%})"
                    if ongoing and before.get(reporter)
                    else ""
                )
                for reporter, n in found.items()
            )
            # A wave still collecting is drawn as long as the one before it took.
            previous = study_config.waves.get(earlier) if earlier else None
            if ongoing and previous and previous.start and previous.end:
                bar["projected"] = dates.start + (previous.end - previous.start)
            lanes.append(lane)
            bars.append(bar)
            earlier = wave
        if study_config.milestones:
            lane = (
                "Milestones"
                if not several_studies(result)
                else f"{study_config.label or study} milestones"
            )
            lanes.append(lane)
            marks += [
                {"lane": lane, "name": m.name, "date": m.date} for m in study_config.milestones
            ]
    return plots.timeline(lanes, bars, marks, today) if bars or marks else None


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


def score_levels(result: CatalogResult) -> go.Figure | None:
    # Scores differ in range, so each mean is shown as its place within the possible range.
    config = result.project.config
    found: dict[tuple[str, str], dict[Member, ResolvedScore]] = {}
    for s in result.catalog.scores:
        d = dataset_by_name(config, s.dataset)
        if summary_of(result, s.key).mean is not None:
            found.setdefault((d.study, d.wave), {})[(s.instrument_id, s.score_id, d.reporter)] = s
    if not found:
        return None
    series = []
    for study, study_config in config.studies.items():
        for wave in sorted(study_config.waves, key=wave_order):
            values, notes = {}, {}
            for member, s in found.get((study, wave), {}).items():
                summary = summary_of(result, s.key)
                low, high = summary.possible_range
                values[member] = (summary.mean - low) / (high - low) if high > low else 0.0
                notes[member] = (
                    f"<br>mean {summary.mean:.2f}, possible {low:g} to {high:g}"
                    f"<br>n = {summary.n_valid}"
                )
            if values:
                series.append(
                    {
                        "name": wave_name(result, study, wave),
                        "color": wave_colors(result)[wave],
                        "values": values,
                        "notes": notes,
                    }
                )
    members = sorted(
        {m for scores in found.values() for m in scores}, key=lambda m: member_rank(result, m)
    )
    labels = dict(zip(members, member_labels(result, members), strict=True))
    names = instrument_names(result)
    blocks = [
        (names[i], [{"id": m, "tick": labels[m], "hover": labels[m]} for m in members if m[0] == i])
        for i in dict.fromkeys(m[0] for m in members)
    ]
    return plots.dot_rows(blocks, series, "% of possible range", "", LEVEL_RANGE, ".0%")


def instrument_names(result: CatalogResult) -> dict[str, str]:
    return {
        i: f"{x.abbreviation}: {x.name}" if x.abbreviation else x.name
        for i, x in result.project.instruments.items()
    }


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
        "scores": resolved_scores,
        "labels": [
            short_label(result.project.instruments[s.instrument_id], d)
            for s, d in zip(resolved_scores, definitions, strict=True)
        ],
        "groups": [s.instrument_id for s in resolved_scores],
        "skip": skip,
    }


def network_colorings(result: CatalogResult) -> dict[str, str]:
    config = result.project.config
    facets = [n for n in facet_names(config) if n not in ("study", "wave")]
    return {
        "instrument": "Instrument",
        "cluster": "Cluster",
        **{f"facet:{n}": facet_label(config, n) for n in facets},
    }


def score_network(
    result: CatalogResult, study: str, wave: str, instruments: list[str], color_by: str
) -> dict | None:
    p = score_panel(result, study, wave, instruments)
    if p is None:
        return None
    z = matrices.as_matrix(p["r"])
    labels = p["labels"]
    pairs = [
        (i, j)
        for i in range(len(labels))
        for j in range(i)
        if (j, i) not in p["skip"] and np.isfinite(z[i, j]) and abs(z[i, j]) >= defaults.CHART_MIN_R
    ]
    degree = Counter(k for pair in pairs for k in pair)
    which, categories, shown = network_groups(result, p, z, color_by)
    names = instrument_names(result)
    nodes = [
        {
            "label": label,
            "category": which[i],
            "tip": "<br>".join(
                part
                for part in (
                    f"<b>{label}</b>",
                    names[p["groups"][i]],
                    shown[i],
                    f"{degree[i]} links",
                )
                if part
            ),
        }
        for i, label in enumerate(labels)
    ]
    links = [
        {
            "source": i,
            "target": j,
            "r": float(z[i, j]),
            "tip": f"{labels[i]} and {labels[j]}<br>r = {z[i, j]:.2f}, n = {p['n'][i][j]}",
        }
        for i, j in pairs
    ]
    note = f"Links: |r| ≥ {defaults.CHART_MIN_R:g}. Drag to move, scroll to zoom."
    return network.score_network(nodes, links, categories, p["title"], note)


def network_groups(
    result: CatalogResult, p: dict, z: np.ndarray, color_by: str
) -> tuple[list[int], list[tuple[str, str]], list[str]]:
    groups = p["groups"]
    if color_by == "instrument":
        order = instrument_order(result)
        present = [i for i in order if i in groups]
        names = instrument_names(result)
        categories = [(names[i], group_color(order.index(i))) for i in present]
        return [present.index(g) for g in groups], categories, [""] * len(groups)
    if color_by == "cluster":
        found = score_clusters(z, p["skip"])
        sizes = Counter(found)
        kept = [c for c in dict.fromkeys(found) if sizes[c] > 1]
        categories = [(f"Cluster {k}", group_color(k - 1)) for k in range(1, len(kept) + 1)]
        if len(kept) < len(sizes):
            categories.append(("Unclustered", network.UNSET_COLOR))
        which = [kept.index(c) if c in kept else len(kept) for c in found]
        return which, categories, [categories[w][0] for w in which]
    config = result.project.config
    name = color_by.removeprefix("facet:")
    values = [score_facet(result, s, name) for s in p["scores"]]
    seen = set().union(*values)
    declared = value_order(config, name)
    order = [v for v in declared if v in seen] + sorted(seen - set(declared))
    # As in Obsidian's groups, a node with several values takes the first one in the declared order.
    which = [next((k for k, v in enumerate(order) if v in vs), len(order)) for vs in values]
    categories = [(v, group_color(k)) for k, v in enumerate(order)]
    if len(order) in which:
        categories.append((network.UNSET, network.UNSET_COLOR))
    label = facet_label(config, name)
    shown = [f"{label}: {', '.join(v for v in order if v in vs) or network.UNSET}" for vs in values]
    return which, categories, shown


def score_clusters(z: np.ndarray, skip: set[tuple[int, int]]) -> list[int]:
    # Average linkage on 1 - |r|, cut where the average |r| between clusters falls below the link threshold.
    d = 1.0 - np.abs(z)
    d[~np.isfinite(d)] = 1.0
    for a, b in skip:
        d[a, b] = d[b, a] = 1.0
    np.fill_diagonal(d, 0.0)
    tree = linkage(squareform(d, checks=False), method="average")
    return [int(c) for c in fcluster(tree, t=1.0 - defaults.CHART_MIN_R, criterion="distance")]


def score_facet(result: CatalogResult, score: ResolvedScore, name: str) -> set[str]:
    config = result.project.config
    dataset = dataset_by_name(config, score.dataset)
    administration = next(
        a
        for content in result.project.studies.values()
        if content.study == dataset.study
        for a in content.administrations
        if a.instrument == score.instrument_id and score.dataset in a.datasets
    )
    known = {
        "reporter": dataset.reporter,
        "target": administration.target,
        "modality": dataset.modality,
    }
    if name in known:
        return as_set(known[name])
    custom = {
        **dataset.custom,
        **result.project.instruments[score.instrument_id].custom,
        **administration.custom,
        **definition(result, score).custom,
    }
    return as_set(custom.get(name))


Member = tuple[str, str, str]


def member_rank(result: CatalogResult, member: Member) -> tuple:
    instrument = result.project.instruments[member[0]]
    score = next(s for s in instrument.scores if s.id == member[1])
    return (
        instrument_order(result).index(member[0]),
        not is_total(instrument, score),
        instrument.scores.index(score),
        member[2],
    )


def member_labels(result: CatalogResult, members: list[Member]) -> list[str]:
    reporters: dict[str, set[str]] = {}
    for instrument_id, _, reporter in members:
        reporters.setdefault(instrument_id, set()).add(reporter)
    labels = []
    for instrument_id, score_id, reporter in members:
        instrument = result.project.instruments[instrument_id]
        label = short_label(instrument, next(s for s in instrument.scores if s.id == score_id))
        labels.append(f"{label} ({reporter})" if len(reporters[instrument_id]) > 1 else label)
    return labels


def score_choices(result: CatalogResult) -> dict[str, str]:
    seen = {(s.instrument_id, s.score_id): s for s in result.catalog.scores}
    return {
        f"{instrument_id}|{score_id}": short_label(
            result.project.instruments[instrument_id], definition(result, s)
        )
        for (instrument_id, score_id), s in seen.items()
    }


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
        # Number and text answers have no response options to sort them by.
        if v.instrument_id == instrument_id
        and v.type == "choice"
        and v.column in result.datasets[dataset].frame
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
    items = [i.id for i in instrument.items if i.type == "choice"]
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
        ("All items", [i.id for i in instrument.items if i.type == "choice"])
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


# ---- analysis page ----


def dataset_label(result: CatalogResult, name: str) -> str:
    d = dataset_by_name(result.project.config, name)
    return f"{name} ({wave_name(result, d.study, d.wave)}, {d.reporter})"


def variable_choices(result: CatalogResult, datasets: list[str]) -> dict[str, str]:
    # Every score and number item of the chosen files, named by wave (and reporter where a wave has several).
    names = series_names(result, modality_order(result, datasets))
    instruments = result.project.instruments
    found = {}
    for name in names:
        for s in result.catalog.scores_for(name):
            found[s.key] = (
                f"{short_label(instruments[s.instrument_id], definition(result, s))} ({names[name]})"
            )
        for v in analysis.number_items(result, [name]):
            instrument = instruments[v.instrument_id]
            text = next(iter(v.text.values()))
            found[analysis.item_key(v)] = (
                f"{instrument.abbreviation or instrument.id}: {text} ({names[name]})"
            )
    return found


def wave_groups(
    result: CatalogResult,
    datasets: list[str],
    choices: Callable[[CatalogResult, list[str]], dict[str, str]],
) -> dict[str, list[str]]:
    # The choices each wave offers on its own, with every reporter of a wave together.
    config = result.project.config
    by_wave: dict[str, list[str]] = {}
    for name in dataset_order(result, datasets):
        d = dataset_by_name(config, name)
        by_wave.setdefault(wave_name(result, d.study, d.wave), []).append(name)
    return {wave: list(choices(result, names)) for wave, names in by_wave.items()}


def modality_order(result: CatalogResult, datasets: list[str]) -> list[str]:
    # Each modality's files together, in the order vocab lists them, waves in order within.
    config = result.project.config
    modalities = config.vocab.modalities

    def rank(name: str) -> int:
        modality = dataset_by_name(config, name).modality
        return modalities.index(modality) if modality in modalities else len(modalities)

    return sorted(dataset_order(result, datasets), key=rank)


def menu_groups(
    result: CatalogResult,
    datasets: list[str],
    choices: Callable[[CatalogResult, list[str]], dict[str, str]],
) -> dict[str, list[str]]:
    # Shortcuts to add a wave's or a modality's choices at once, where there is more than one.
    config = result.project.config
    waves = wave_groups(result, datasets, choices)
    found = {f"All in {wave}": keys for wave, keys in waves.items()} if len(waves) > 1 else {}
    by_modality: dict[str, list[str]] = {}
    for name in modality_order(result, datasets):
        by_modality.setdefault(dataset_by_name(config, name).modality, []).append(name)
    if len(by_modality) > 1:
        for modality, names in by_modality.items():
            keys = list(choices(result, names))
            if keys:
                found[f"All {config.vocab.modality_label(modality)}"] = keys
    return found


def total_choices(result: CatalogResult, datasets: list[str]) -> list[str]:
    found = []
    for key in variable_choices(result, datasets):
        if key.startswith(analysis.ITEM_PREFIX):
            continue
        score = score_of(result, key)
        if is_total(result.project.instruments[score.instrument_id], definition(result, score)):
            found.append(key)
    return found


def score_of(result: CatalogResult, key: str) -> ResolvedScore:
    return next(s for s in result.catalog.scores if s.key == key)


def correlation_chart(
    result: CatalogResult,
    keys: list[str],
    matrix: list[list[analysis.Correlation]],
    labels: list[str],
    style: str = "heatmap",
) -> go.Figure | None:
    z = matrices.as_matrix([[c.r for c in row] for row in matrix])
    hover = [
        [
            f"{labels[i]} × {labels[j]}<br>r = {c.r:.2f}, n = {c.n}, "
            + ("p < .001" if c.p < 0.001 else f"p = {c.p:.3f}")
            if c.r is not None
            else ""
            for j, c in enumerate(row)
        ]
        for i, row in enumerate(matrix)
    ]
    if style == "dots":
        return matrices.dot_matrix(
            z,
            labels,
            hover,
            [analysis.instrument_of(k) for k in keys],
            instrument_order(result),
            instrument_names(result),
            "Pearson r",
        )
    return matrices.heatmap(z, labels, hover, "Pearson r")


def pair_scatter(
    result: CatalogResult, sample: analysis.Sample, xs: list[str], y: str
) -> go.Figure | None:
    # One group per X against the same Y, each with the people who have both.
    labels = variable_choices(result, sample.datasets)
    groups = []
    for k, x in enumerate(xs):
        frame = analysis.table(result, sample, [x, y]).dropna()
        if len(frame) < defaults.MIN_CORRELATION_N:
            continue
        groups.append(
            {
                "name": labels[x],
                "color": group_color(k),
                "x": frame[x].to_numpy(dtype=float),
                "y": frame[y].to_numpy(dtype=float),
                "ids": [str(i) for i in frame.index],
            }
        )
    if not groups:
        return None
    x_title = groups[0]["name"] if len(groups) == 1 else "X (see legend)"
    return scatter.regression(x_title, labels[y], groups)
