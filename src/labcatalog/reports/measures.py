from collections.abc import Callable

from labcatalog.config import dataset_by_name
from labcatalog.data.resolve import Catalog, ResolvedScore
from labcatalog.metadata.bibliography import in_text
from labcatalog.project import Project
from labcatalog.reports import templates
from labcatalog.reports.templates import Wording
from labcatalog.schema import SCRIPT, Instrument
from labcatalog.stats.cfa import WLSMV, CfaFit
from labcatalog.stats.summary import Summary

KEY = "measures"
# APA writes numbers below ten as words.
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def wording_for(project: Project, instrument: Instrument) -> Wording:
    return templates.layered(project.config, KEY, instrument.measures)


def paragraph(
    project: Project,
    catalog: Catalog,
    summary: Summary,
    instrument: Instrument,
    dataset: str,
    fits: list[CfaFit],
    wording: Wording | None = None,
) -> str:
    wording = wording or wording_for(project, instrument)
    values = placeholder_values(project, catalog, summary, instrument, dataset, fits, wording)
    return wording.say(KEY, templates.PARAGRAPH, **values)


def paragraphs(
    project: Project, catalog: Catalog, summary: Summary, pairs: list[tuple[str, str]]
) -> list[str]:
    # Each instrument as given in each dataset, in the order of the pairs; ω needs the factor models.
    administered = {(v.instrument_id, v.dataset) for v in catalog.variables}
    return [
        paragraph(project, catalog, summary, project.instruments[instrument_id], dataset, [])
        for instrument_id, dataset in dict.fromkeys(pairs)
        if (instrument_id, dataset) in administered
    ]


def placeholder_values(
    project: Project,
    catalog: Catalog,
    summary: Summary,
    instrument: Instrument,
    dataset: str,
    fits: list[CfaFit],
    wording: Wording,
) -> dict[str, str]:
    def say(slot: str, **values: object) -> str:
        return wording.say(KEY, slot, **values)

    cite = "; ".join(in_text(project.bibliography, r.key) for r in instrument.references)
    inside = "; ".join(p for p in (instrument.abbreviation, cite) if p)
    administered = {
        v.item_id for v in catalog.variables_for(dataset) if v.instrument_id == instrument.id
    }
    items = [item for item in instrument.items if item.id in administered]
    scale = response_scale(instrument, items, say)
    if instrument.abbreviation:
        subject = say("subject", abbreviation=instrument.abbreviation)
    else:
        subject = say("subject_plain")
    n_items = number(len(items))
    scores = [s for s in catalog.scores if s.instrument_id == instrument.id]
    scores = [s for s in scores if s.dataset == dataset]
    alphas = {
        s.label: found.alpha
        for s in scores
        for found in summary.scores
        if found.key == s.key and found.alpha is not None
    }
    omega = {score: value for f in fits for score, value in f.omega.items()}
    omegas = {s.label: omega[s.score_id] for s in scores if s.score_id in omega}
    ordinal = any(f.estimator == WLSMV for f in fits)
    if inside:
        named = say("named", name=instrument.name, details=inside)
    else:
        named = say("named_plain", name=instrument.name)
    if scale:
        counted = say("items", subject=subject, n_items=n_items, scale=scale)
    else:
        counted = say("items_plain", subject=subject, n_items=n_items)
    return {
        "name": instrument.name,
        "abbreviation": instrument.abbreviation or "",
        "cite": cite,
        "named": named,
        "construct": instrument.construct_name or "",
        "reporter": dataset_by_name(project.config, dataset).reporter,
        "n_items": n_items,
        "scale": scale,
        "description": instrument.description or "",
        "items": counted,
        "reverse": reversed_items(instrument, administered, say),
        "scoring": scoring(scores, say),
        "alpha": reliability("Cronbach's α", alphas, say),
        "omega": reliability("Categorical ω" if ordinal else "McDonald's ω", omegas, say),
    }


def response_scale(instrument: Instrument, items: list, say: Callable[..., str]) -> str:
    sets = {item.response_set or instrument.default_response_set for item in items}
    if any(item.type != "choice" for item in items) or len(sets) != 1:
        return ""
    options = next(s for s in instrument.response_sets if s.id in sets).options
    first, last = options[0], options[-1]
    return say(
        "scale", low=first.value, low_label=first.label, high=last.value, high_label=last.label
    )


def reversed_items(instrument: Instrument, administered: set[str], say: Callable[..., str]) -> str:
    found = [
        str(n)
        for n, item in enumerate(instrument.items, start=1)
        if item.reverse and item.id in administered
    ]
    if not found:
        return ""
    if len(found) == 1:
        return say("reverse_one", items=found[0])
    return say("reverse_many", items=series(found))


def scoring(scores: list[ResolvedScore], say: Callable[..., str]) -> str:
    by_method: dict[str, list[str]] = {}
    for s in scores:
        if s.method == SCRIPT:
            named = s.label
        else:
            named = say("score", score=s.label, n_items=number(len(s.columns)))
        by_method.setdefault(s.method, []).append(named)
    if not by_method:
        return ""
    parts = [
        say("scoring_script", scores=series(named))
        if method == SCRIPT
        else say("scoring_method", method=method, scores=series(named))
        for method, named in by_method.items()
    ]
    return say("scoring", parts=series(parts))


def reliability(statistic: str, values: dict[str, float], say: Callable[..., str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return say(
            "reliability_one", statistic=statistic, value=bounded(next(iter(values.values())))
        )
    found = [say("reliability_each", value=bounded(v), score=label) for label, v in values.items()]
    return say("reliability_many", statistic=statistic, values=series(found))


def bounded(value: float) -> str:
    # Values that cannot exceed 1 drop the leading zero.
    return f"{value:.2f}".replace("0.", ".", 1)


def number(n: int) -> str:
    return WORDS[n] if n < len(WORDS) else str(n)


def series(parts: list[str]) -> str:
    if len(parts) < 3:
        return " and ".join(parts)
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"
