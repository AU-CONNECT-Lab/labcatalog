from dataclasses import dataclass

from labcatalog import defaults
from labcatalog.config import ProjectConfig, dataset_by_name
from labcatalog.project import Project
from labcatalog.resolve import as_text_dict
from labcatalog.schema import Instrument
from labcatalog.stats import wave_order


@dataclass
class Facet:
    name: str
    label: str
    # Value key to display label, in display order; only values that occur are listed.
    values: dict[str, str]


@dataclass
class Administered:
    instrument_id: str
    dataset: str | None
    values: dict[str, set[str]]


@dataclass
class BrowseIndex:
    instruments: list[str]
    facets: list[Facet]
    rows: list[Administered]
    text: dict[str, str]
    item_text: dict[str, str]


def facet_names(config: ProjectConfig) -> list[str]:
    if config.browse.facets is not None:
        return config.browse.facets
    custom = [f.name for f in config.custom_fields if f.type in defaults.FACET_FIELD_TYPES]
    return [*defaults.DEFAULT_FACETS, *custom]


def wave_key(study: str, wave: str) -> str:
    return f"{study}/{wave}"


def build_index(project: Project) -> BrowseIndex:
    config = project.config
    names = facet_names(config)
    rows = []
    for content in project.studies.values():
        for administration in content.administrations:
            instrument = project.instruments[administration.instrument]
            for name in administration.datasets:
                dataset = dataset_by_name(config, name)
                known = {
                    "study": dataset.study,
                    "wave": wave_key(dataset.study, dataset.wave),
                    "reporter": dataset.reporter,
                    "target": administration.target,
                    "modality": dataset.modality,
                }
                custom = {**dataset.custom, **instrument.custom, **administration.custom}
                values = {n: as_set(known[n] if n in known else custom.get(n)) for n in names}
                rows.append(Administered(instrument.id, name, values))
    administered = {row.instrument_id for row in rows}
    for instrument_id, instrument in project.instruments.items():
        if instrument_id not in administered:
            values = {n: as_set(instrument.custom.get(n)) for n in names}
            rows.append(Administered(instrument_id, None, values))
    return BrowseIndex(
        instruments=list(project.instruments),
        facets=[facet(config, name, rows) for name in names],
        rows=rows,
        text={i: search_text(instrument) for i, instrument in project.instruments.items()},
        item_text={
            i: "\n".join(
                text for item in instrument.items for text in as_text_dict(item.text).values()
            ).lower()
            for i, instrument in project.instruments.items()
        },
    )


def matches(
    index: BrowseIndex, selected: dict[str, set[str]], query: str = "", items: bool = False
) -> dict[str, list[str]]:
    allowed = text_matches(index, query, items)
    found: dict[str, list[str]] = {}
    for row in index.rows:
        if row.instrument_id in allowed and row_selected(row, selected):
            datasets = found.setdefault(row.instrument_id, [])
            if row.dataset is not None:
                datasets.append(row.dataset)
    return {i: found[i] for i in index.instruments if i in found}


def counts(
    index: BrowseIndex, selected: dict[str, set[str]], query: str = "", items: bool = False
) -> dict[str, dict[str, int]]:
    # Each facet is counted with the other facets applied, so its own values stay alternatives.
    allowed = text_matches(index, query, items)
    result = {}
    for facet in index.facets:
        others = {name: chosen for name, chosen in selected.items() if name != facet.name}
        hits: dict[str, set[str]] = {value: set() for value in facet.values}
        for row in index.rows:
            if row.instrument_id in allowed and row_selected(row, others):
                for value in row.values[facet.name]:
                    hits[value].add(row.instrument_id)
        result[facet.name] = {value: len(ids) for value, ids in hits.items()}
    return result


def row_selected(row: Administered, selected: dict[str, set[str]]) -> bool:
    return all(not chosen or row.values[name] & chosen for name, chosen in selected.items())


def text_matches(index: BrowseIndex, query: str, items: bool) -> set[str]:
    terms = query.lower().split()
    return {
        i
        for i in index.instruments
        if all(term in index.text[i] or (items and term in index.item_text[i]) for term in terms)
    }


def search_text(instrument: Instrument) -> str:
    parts = [instrument.id, instrument.name, instrument.abbreviation, instrument.construct_name]
    parts += [value for values in instrument.custom.values() for value in as_set(values)]
    return "\n".join(part for part in parts if part).lower()


def as_set(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list):
        return {str(v) for v in value}
    return {str(value)}


def facet(config: ProjectConfig, name: str, rows: list[Administered]) -> Facet:
    present = {value for row in rows for value in row.values[name]}
    if name == "study":
        labels = {s: study.label or s for s, study in config.studies.items()}
    elif name == "wave":
        several = len(config.studies) > 1
        labels = {
            wave_key(s, wave): f"{study.label or s}: {wave}" if several else wave
            for s, study in config.studies.items()
            for wave in sorted(study.waves, key=wave_order)
        }
    elif name in defaults.BUILTIN_FACETS:
        vocab = config.vocab
        order = {"reporter": vocab.reporters, "target": vocab.targets, "modality": vocab.modalities}
        labels = {v: v for v in order[name]}
    else:
        field = next(f for f in config.custom_fields if f.name == name)
        labels = {v: v for v in field.choices or []}
    labels.update({v: v for v in sorted(present - set(labels))})
    return Facet(
        name=name,
        label=facet_label(config, name),
        values={value: label for value, label in labels.items() if value in present},
    )


def facet_label(config: ProjectConfig, name: str) -> str:
    if name in defaults.BUILTIN_FACETS:
        return "About" if name == "target" else name.capitalize()
    field = next(f for f in config.custom_fields if f.name == name)
    return field.label or name.capitalize()
