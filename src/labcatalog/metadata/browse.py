from dataclasses import dataclass, field

from labcatalog import defaults
from labcatalog.config import ProjectConfig, dataset_by_name
from labcatalog.data.resolve import as_text_dict
from labcatalog.metadata.completeness import gaps
from labcatalog.project import Project
from labcatalog.schema import Instrument
from labcatalog.stats.summary import wave_order

EVERY_WAVE = "every wave"
COMPLETE = "complete"
NOT_GIVEN = "not in a dataset"


@dataclass
class Facet:
    name: str
    label: str
    # Value key to display label, in display order; only values that occur are listed.
    values: dict[str, str]
    # A vocabulary's terms, to the group they are listed under.
    parents: dict[str, str] = field(default_factory=dict)


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
    return [*defaults.DEFAULT_FACETS, *custom, *defaults.DEFAULT_LAST_FACETS]


def wave_key(study: str, wave: str) -> str:
    return f"{study}/{wave}"


def build_index(project: Project) -> BrowseIndex:
    config = project.config
    names = facet_names(config)
    coverage = wave_coverage(project)
    status = {
        i: [f"no {gap}" for gap in gaps(s)] or [COMPLETE] for i, s in project.instruments.items()
    }
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
                    "coverage": coverage[(instrument.id, dataset.study)],
                    "status": status[instrument.id],
                }
                custom = {
                    **part_values(instrument),
                    **config.studies[dataset.study].custom,
                    **dataset.custom,
                    **instrument.custom,
                    **administration.custom,
                }
                values = {n: as_set(known[n] if n in known else custom.get(n)) for n in names}
                rows.append(Administered(instrument.id, name, widened(config, values)))
    administered = {row.instrument_id for row in rows}
    # Data column names find their instrument, as its ID does.
    columns: dict[str, set[str]] = {}
    for entries in project.maps.values():
        for entry in entries:
            if entry.instrument:
                columns.setdefault(entry.instrument, set()).add(entry.column)
    roster = project.config.roster.instrument if project.config.roster else None
    for instrument_id, instrument in project.instruments.items():
        if instrument_id not in administered:
            # The roster's instrument is in the data, though in no dataset.
            unused = [] if instrument_id == roster else [NOT_GIVEN]
            custom = {
                **part_values(instrument),
                **instrument.custom,
                "status": [*status[instrument_id], *unused],
            }
            values = {n: as_set(custom.get(n)) for n in names}
            rows.append(Administered(instrument_id, None, widened(config, values)))
    return BrowseIndex(
        instruments=list(project.instruments),
        facets=[facet(config, name, rows) for name in names],
        rows=rows,
        text={
            i: "\n".join([search_text(instrument), *sorted(columns.get(i, ()))]).lower()
            for i, instrument in project.instruments.items()
        },
        item_text={
            i: "\n".join(
                text for item in instrument.items for text in as_text_dict(item.text).values()
            ).lower()
            for i, instrument in project.instruments.items()
        },
    )


def wave_coverage(project: Project) -> dict[tuple[str, str], str]:
    # Counted against the waves of the study that have data, so a planned wave does not count.
    config = project.config
    waves: dict[str, set[str]] = {}
    for d in config.datasets:
        waves.setdefault(d.study, set()).add(d.wave)
    given: dict[tuple[str, str], set[str]] = {}
    for content in project.studies.values():
        for administration in content.administrations:
            for name in administration.datasets:
                d = dataset_by_name(config, name)
                given.setdefault((administration.instrument, d.study), set()).add(d.wave)
    return {
        key: EVERY_WAVE if found == waves[key[1]] else waves_label(len(found))
        for key, found in given.items()
    }


def waves_label(n: int) -> str:
    return f"{n} wave" if n == 1 else f"{n} waves"


def matches(
    index: BrowseIndex,
    selected: dict[str, set[str]],
    query: str = "",
    items: bool = False,
    only: set[str] | None = None,
) -> dict[str, list[str]]:
    allowed = text_matches(index, query, items, only)
    found: dict[str, list[str]] = {}
    for row in index.rows:
        if row.instrument_id in allowed and row_selected(row, selected):
            datasets = found.setdefault(row.instrument_id, [])
            if row.dataset is not None:
                datasets.append(row.dataset)
    return {i: found[i] for i in index.instruments if i in found}


def counts(
    index: BrowseIndex,
    selected: dict[str, set[str]],
    query: str = "",
    items: bool = False,
    only: set[str] | None = None,
) -> dict[str, dict[str, int]]:
    # Each facet is counted with the other facets applied, so its own values stay alternatives.
    allowed = text_matches(index, query, items, only)
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


def text_matches(
    index: BrowseIndex, query: str, items: bool, only: set[str] | None = None
) -> set[str]:
    # only: the instruments a language-model search found, applied on top of the words.
    terms = query.lower().split()
    return {
        i
        for i in index.instruments
        if (only is None or i in only)
        and all(term in index.text[i] or (items and term in index.item_text[i]) for term in terms)
    }


def search_text(instrument: Instrument) -> str:
    parts = [instrument.id, instrument.name, instrument.abbreviation, instrument.construct_name]
    custom = {**part_values(instrument), **instrument.custom}
    parts += [value for values in custom.values() for value in as_set(values)]
    return "\n".join(part for part in parts if part).lower()


def part_values(instrument: Instrument) -> dict[str, list[str]]:
    # Its scores' and items' field values also describe an instrument, so a filter finds it by them.
    found: dict[str, set[str]] = {}
    for part in [*instrument.scores, *instrument.items]:
        for name, value in part.custom.items():
            found.setdefault(name, set()).update(as_set(value))
    return {name: sorted(values) for name, values in found.items()}


def widened(config: ProjectConfig, values: dict[str, set[str]]) -> dict[str, set[str]]:
    # A vocabulary's term also counts as its group, so choosing the group finds it.
    for custom in config.custom_fields:
        parents = custom.parents()
        if custom.name in values and parents:
            found = values[custom.name]
            values[custom.name] = found | {parents[v] for v in found if v in parents}
    return values


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
    elif name == "modality":
        labels = {v: config.vocab.modality_label(v) for v in config.vocab.modalities}
    elif name == "coverage":
        sizes = sorted({int(v.split()[0]) for v in present if v != EVERY_WAVE}, reverse=True)
        labels = {v: v for v in [EVERY_WAVE, *(waves_label(n) for n in sizes)]}
    elif name == "status":
        labels = {v: v for v in [COMPLETE, *sorted(present - {COMPLETE, NOT_GIVEN}), NOT_GIVEN]}
    else:
        labels = {v: v for v in value_order(config, name)}
    labels.update({v: v for v in sorted(present - set(labels))})
    custom = next((f for f in config.custom_fields if f.name == name), None)
    parents = custom.parents() if custom is not None else {}
    return Facet(
        name=name,
        label=facet_label(config, name),
        values={value: label for value, label in labels.items() if value in present},
        parents={v: p for v, p in parents.items() if v in present},
    )


def value_order(config: ProjectConfig, name: str) -> list[str]:
    if name in defaults.BUILTIN_FACETS:
        vocab = config.vocab
        return {"reporter": vocab.reporters, "target": vocab.targets, "modality": vocab.modalities}[
            name
        ]
    field = next(f for f in config.custom_fields if f.name == name)
    return field.choices or []


def facet_label(config: ProjectConfig, name: str) -> str:
    if name in defaults.BUILTIN_FACETS:
        named = {"target": "About", "coverage": "Given in", "status": "Catalog"}
        return named.get(name, name.capitalize())
    field = next(f for f in config.custom_fields if f.name == name)
    return field.label or name.capitalize()
