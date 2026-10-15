from collections.abc import Callable

from nicegui import ui

from labcatalog.browse import facet_names
from labcatalog.config import WaveConfig
from labcatalog.gui import charts
from labcatalog.gui.common import (
    as_list,
    as_text,
    col,
    heading,
    keyed,
    sorted_waves,
    table,
    unique,
)
from labcatalog.pipeline import CatalogResult


def render(
    result: CatalogResult, on_instrument: Callable[[str], None], on_problems: Callable[[], None]
) -> None:
    issues = result.report.issues
    with ui.row().classes("gap-4"):
        stat("Instruments", len(result.project.instruments))
        stat("Datasets", len(result.project.config.datasets))
        stat("Errors", sum(i.level == "error" for i in issues), on_problems)
        stat("Warnings", sum(i.level == "warning" for i in issues), on_problems)

    heading("Waves")
    table(*wave_table(result))

    charts.overview_section(result)

    heading("Instruments")
    instrument_list(result, on_instrument)

    heading("Who answered each instrument")
    table(*availability_table(result))


def stat(label: str, value: int, on_click: Callable[[], None] | None = None) -> None:
    card = ui.card().classes("min-w-32 px-4 py-2 gap-0")
    if on_click is not None:
        card.classes("cursor-pointer").on("click", on_click)
    with card:
        ui.label(str(value)).classes("text-2xl font-medium")
        ui.label(label).classes("text-grey-7")


def instrument_list(result: CatalogResult, on_instrument: Callable[[str], None]) -> None:
    columns, rows = instrument_table(result)
    labels, values = instrument_filters(result)
    with ui.row().classes("w-full items-center gap-4"):
        search = ui.input(placeholder="Search").props("dense clearable").classes("w-64")
        selects = {
            key: ui.select(
                sorted(set().union(*(v[key] for v in values.values()))),
                label=label,
                clearable=True,
            )
            .props("dense")
            .classes("w-48")
            for key, label in labels.items()
        }
    shown = table(columns, rows)
    shown.classes("cursor-pointer")
    search.bind_value_to(shown, "filter")
    shown.on("rowClick", lambda e: on_instrument(e.args[1]["id"]))

    def apply_filters() -> None:
        chosen = {key: s.value for key, s in selects.items() if s.value}
        matching = [r for r in rows if all(v in values[r["id"]][key] for key, v in chosen.items())]
        shown.update_rows(keyed(matching))

    for select in selects.values():
        select.on_value_change(apply_filters)


def wave_table(result: CatalogResult) -> tuple[list[dict], list[dict]]:
    config, summary = result.project.config, result.summary
    reporters = unique(r.reporter for r in summary.retention)
    counts = {(r.study, r.wave, r.reporter): r.n for r in summary.retention}
    groups = {(g.study, g.wave): g for g in summary.groups}
    group = summary.group_name
    columns = [
        col("study", "Study"),
        col("wave", "Wave"),
        col("dates", "Dates", sortable=False),
        *[col(f"n_{r}", r.capitalize(), numeric=True) for r in reporters],
    ]
    if group:
        columns += [
            col("groups", f"{group.capitalize()} groups", numeric=True),
            col("complete_groups", "With every reporter", numeric=True),
        ]
    rows = []
    for study, study_config in config.studies.items():
        for wave in sorted_waves(study_config.waves):
            found = groups.get((study, wave))
            rows.append(
                {
                    "study": study_config.label or study,
                    "wave": wave,
                    "dates": wave_dates(study_config.waves[wave]),
                    **{f"n_{r}": counts.get((study, wave, r), "") for r in reporters},
                    "groups": found.groups if found else "",
                    "complete_groups": found.with_every_reporter if found else "",
                }
            )
    return columns, rows


def wave_dates(wave: WaveConfig) -> str:
    if wave.start and wave.end:
        return f"{wave.start} to {wave.end}"
    if wave.start:
        return f"since {wave.start}"
    if wave.end:
        return f"until {wave.end}"
    return ""


def instrument_table(result: CatalogResult) -> tuple[list[dict], list[dict]]:
    project = result.project
    fields = instrument_fields(result)
    columns = [
        col("abbreviation", "Abbr."),
        col("name", "Name"),
        col("construct", "Construct"),
        col("reporters", "Reporter"),
        col("targets", "About"),
        col("waves", "Waves"),
        col("items", "Items", numeric=True),
        *[col(f"custom_{f.name}", f.label or f.name.capitalize()) for f in fields],
    ]
    rows = []
    for instrument_id, instrument in project.instruments.items():
        variables = [v for v in result.catalog.variables if v.instrument_id == instrument_id]
        rows.append(
            {
                "id": instrument_id,
                "abbreviation": instrument.abbreviation or "",
                "name": instrument.name,
                "construct": instrument.construct_name or "",
                "reporters": ", ".join(unique(v.reporter for v in variables)),
                "targets": ", ".join(unique(v.target for v in variables if v.target)),
                "waves": ", ".join(sorted_waves(v.wave for v in variables)),
                "items": len(instrument.items),
                **{f"custom_{f.name}": as_text(instrument.custom.get(f.name)) for f in fields},
            }
        )
    return columns, rows


def instrument_fields(result: CatalogResult) -> list:
    return [f for f in result.project.config.custom_fields if f.applies_to == "instrument"]


def instrument_filters(
    result: CatalogResult,
) -> tuple[dict[str, str], dict[str, dict[str, set[str]]]]:
    facets = facet_names(result.project.config)
    fields = [f for f in instrument_fields(result) if f.name in facets]
    labels = {
        "reporter": "Reporter",
        **{f"custom_{f.name}": f.label or f.name.capitalize() for f in fields},
    }
    values = {
        instrument_id: {
            "reporter": {
                v.reporter for v in result.catalog.variables if v.instrument_id == instrument_id
            },
            **{f"custom_{f.name}": set(as_list(instrument.custom.get(f.name))) for f in fields},
        }
        for instrument_id, instrument in result.project.instruments.items()
    }
    return labels, values


def availability_table(result: CatalogResult) -> tuple[list[dict], list[dict]]:
    answered = {
        (c.instrument_id, d.dataset): c.complete + c.partial
        for d in result.summary.datasets
        for c in d.completeness
    }
    datasets = unique(dataset for _, dataset in answered)
    columns = [
        col("instrument", "Instrument"),
        *[col(f"d{i}", name, numeric=True) for i, name in enumerate(datasets)],
    ]
    rows = [
        {
            "instrument": instrument.abbreviation or instrument_id,
            **{f"d{i}": answered.get((instrument_id, name), "") for i, name in enumerate(datasets)},
        }
        for instrument_id, instrument in result.project.instruments.items()
    ]
    return columns, rows
