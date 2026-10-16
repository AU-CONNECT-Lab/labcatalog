import string

from labcatalog.config import dataset_by_name
from labcatalog.data.resolve import Catalog, ResolvedScore
from labcatalog.metadata.bibliography import in_text
from labcatalog.project import Project
from labcatalog.schema import Instrument
from labcatalog.stats.summary import Summary

DEFAULT_TEMPLATE = "We used {named}. {description} {items} {reverse} {scoring} {alpha} {omega}"
PLACEHOLDERS = (
    "name",
    "abbreviation",
    "cite",
    "named",
    "construct",
    "reporter",
    "n_items",
    "scale",
    "description",
    "items",
    "reverse",
    "scoring",
    "alpha",
    "omega",
)
# APA writes numbers below ten as words.
WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def template_for(project: Project, instrument: Instrument) -> str:
    return instrument.measures or project.config.measures or DEFAULT_TEMPLATE


def placeholder_problem(template: str, allowed: tuple[str, ...]) -> str | None:
    try:
        fields = [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]
    except ValueError as e:
        return f"{e}; write a literal brace as {{{{ or }}}}"
    wrong = [f for f in fields if f not in allowed]
    if wrong:
        return f"unknown placeholder {{{wrong[0]}}}; use one of {', '.join(allowed)}"
    return None


def paragraph(
    project: Project,
    catalog: Catalog,
    summary: Summary,
    instrument: Instrument,
    dataset: str,
    omega: dict[str, float],
) -> str:
    values = placeholder_values(project, catalog, summary, instrument, dataset, omega)
    text = template_for(project, instrument).format_map(values)
    return " ".join(text.split())


def placeholder_values(
    project: Project,
    catalog: Catalog,
    summary: Summary,
    instrument: Instrument,
    dataset: str,
    omega: dict[str, float],
) -> dict[str, str]:
    cite = "; ".join(in_text(project.bibliography, r.key) for r in instrument.references)
    inside = "; ".join(p for p in (instrument.abbreviation, cite) if p)
    administered = {
        v.item_id for v in catalog.variables_for(dataset) if v.instrument_id == instrument.id
    }
    items = [item for item in instrument.items if item.id in administered]
    scale = response_scale(instrument, items)
    subject = f"The {instrument.abbreviation}" if instrument.abbreviation else "The scale"
    counted = f"{subject} has {number(len(items))} items"
    scores = [s for s in catalog.scores if s.instrument_id == instrument.id]
    scores = [s for s in scores if s.dataset == dataset]
    alphas = {
        s.label: found.alpha
        for s in scores
        for found in summary.scores
        if found.key == s.key and found.alpha is not None
    }
    omegas = {s.label: omega[s.score_id] for s in scores if s.score_id in omega}
    return {
        "name": instrument.name,
        "abbreviation": instrument.abbreviation or "",
        "cite": cite,
        "named": f"the {instrument.name}" + (f" ({inside})" if inside else ""),
        "construct": instrument.construct_name or "",
        "reporter": dataset_by_name(project.config, dataset).reporter,
        "n_items": number(len(items)),
        "scale": scale,
        "description": instrument.description or "",
        "items": f"{counted}, each answered from {scale}." if scale else f"{counted}.",
        "reverse": reversed_items(instrument, administered),
        "scoring": scoring(scores),
        "alpha": reliability("Cronbach's α", alphas),
        "omega": reliability("Categorical ω", omegas),
    }


def response_scale(instrument: Instrument, items: list) -> str:
    sets = {item.response_set or instrument.default_response_set for item in items}
    if any(item.type != "choice" for item in items) or len(sets) != 1:
        return ""
    options = next(s for s in instrument.response_sets if s.id in sets).options
    first, last = options[0], options[-1]
    return f"{first.value} ({first.label}) to {last.value} ({last.label})"


def reversed_items(instrument: Instrument, administered: set[str]) -> str:
    found = [
        str(n)
        for n, item in enumerate(instrument.items, start=1)
        if item.reverse and item.id in administered
    ]
    if not found:
        return ""
    if len(found) == 1:
        return f"Item {found[0]} is reverse-scored."
    return f"Items {series(found)} are reverse-scored."


def scoring(scores: list[ResolvedScore]) -> str:
    by_method: dict[str, list[str]] = {}
    for s in scores:
        by_method.setdefault(s.method, []).append(f"{s.label} ({number(len(s.columns))} items)")
    if not by_method:
        return ""
    parts = [
        f"the {method} of the items for {series(named)}" for method, named in by_method.items()
    ]
    return f"Scores are {series(parts)}."


def reliability(statistic: str, values: dict[str, float]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return f"{statistic} was {bounded(next(iter(values.values())))}."
    found = [f"{bounded(v)} for {label}" for label, v in values.items()]
    return f"{statistic} was {series(found)}."


def bounded(value: float) -> str:
    # Values that cannot exceed 1 drop the leading zero.
    return f"{value:.2f}".replace("0.", ".", 1)


def number(n: int) -> str:
    return WORDS[n] if n < len(WORDS) else str(n)


def series(parts: list[str]) -> str:
    if len(parts) < 3:
        return " and ".join(parts)
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"
