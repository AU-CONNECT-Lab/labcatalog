from collections.abc import Callable

from nicegui import ui

from labcatalog.config import dataset_by_name, missing_codes_for
from labcatalog.gui.common import as_text, col, fmt, heading, note, table, unique
from labcatalog.pipeline import CatalogResult
from labcatalog.resolve import as_text_dict
from labcatalog.schema import Instrument, Text


def render(result: CatalogResult, selected: str | None, on_select: Callable[[str], None]) -> None:
    instruments = result.project.instruments
    selected = selected if selected in instruments else next(iter(instruments))
    ui.select(
        {i: label(instrument) for i, instrument in instruments.items()},
        value=selected,
        with_input=True,
        on_change=lambda e: on_select(e.value),
    ).props("dense outlined").classes("w-96")
    instrument = instruments[selected]

    about(result, instrument)

    heading("Items")
    table(*item_table(result, instrument))

    with ui.row().classes("w-full gap-8"):
        for response_set in instrument.response_sets:
            with ui.column().classes("gap-1"):
                heading(f"Options: {response_set.id}")
                table(
                    [col("value", "Value", numeric=True), col("label", "Label")],
                    [o.model_dump() for o in response_set.options],
                ).classes(remove="w-full")
        with ui.column().classes("gap-1"):
            heading("Missing codes")
            table(*missing_code_table(result, instrument)).classes(remove="w-full")

    datasets = administered_in(result, instrument.id)
    if not datasets:
        return
    heading("Statistics")

    @ui.refreshable
    def statistics(dataset: str) -> None:
        dataset_statistics(result, instrument, dataset)

    ui.toggle(datasets, value=datasets[0], on_change=lambda e: statistics.refresh(e.value)).props(
        "dense no-caps"
    )
    statistics(datasets[0])


def label(instrument: Instrument) -> str:
    return (
        f"{instrument.abbreviation}: {instrument.name}"
        if instrument.abbreviation
        else instrument.name
    )


def about(result: CatalogResult, instrument: Instrument) -> None:
    variables = [v for v in result.catalog.variables if v.instrument_id == instrument.id]
    ui.label(instrument.name).classes("text-2xl font-medium mt-4")
    facts = [
        instrument.abbreviation,
        instrument.construct_name,
        reported(variables),
        *[
            f"{f.label or f.name.capitalize()}: {as_text(instrument.custom[f.name])}"
            for f in result.project.config.custom_fields
            if f.applies_to == "instrument" and f.name in instrument.custom
        ],
    ]
    note(" · ".join(fact for fact in facts if fact))
    if instrument.instructions:
        ui.label(text_of(instrument.instructions)).classes("italic")
    for reference in instrument.references:
        with ui.row().classes("items-baseline gap-2"):
            ui.label(reference.citation)
            if reference.doi:
                ui.link("DOI", f"https://doi.org/{reference.doi}", new_tab=True)
            if reference.url:
                ui.link("Link", reference.url, new_tab=True)
    if instrument.license:
        note(f"License: {instrument.license}")


def reported(variables: list) -> str:
    pairs = unique(f"{v.reporter} about {v.target}" if v.target else v.reporter for v in variables)
    return f"Reported by {', '.join(pairs)}" if pairs else ""


def text_of(text: Text) -> str:
    return " / ".join(as_text_dict(text).values())


def administered_in(result: CatalogResult, instrument_id: str) -> list[str]:
    return unique(v.dataset for v in result.catalog.variables if v.instrument_id == instrument_id)


def item_table(result: CatalogResult, instrument: Instrument) -> tuple[list[dict], list[dict]]:
    datasets = administered_in(result, instrument.id)
    columns_by_item = {
        (v.item_id, v.dataset): v.column
        for v in result.catalog.variables
        if v.instrument_id == instrument.id
    }
    several_sets = len(instrument.response_sets) > 1
    columns = [
        col("n", "#", numeric=True),
        col("item", "Item"),
        col("text", "Text", sortable=False),
        col("reverse", "Reverse"),
        *([col("options", "Options")] if several_sets else []),
        *[col(f"d{i}", name) for i, name in enumerate(datasets)],
    ]
    rows = [
        {
            "n": n,
            "item": item.id,
            "text": text_of(item.text),
            "reverse": "yes" if item.reverse else "",
            "options": item.response_set or instrument.default_response_set or "",
            **{
                f"d{i}": columns_by_item.get((item.id, name), "") for i, name in enumerate(datasets)
            },
        }
        for n, item in enumerate(instrument.items, start=1)
    ]
    return columns, rows


def missing_code_table(
    result: CatalogResult, instrument: Instrument
) -> tuple[list[dict], list[dict]]:
    config = result.project.config
    datasets = administered_in(result, instrument.id)
    used: dict[tuple[str, str], list[str]] = {}
    for name in datasets:
        for code in missing_codes_for(config, dataset_by_name(config, name)):
            used.setdefault((str(code.code), code.label), []).append(name)
    columns = [col("code", "Code"), col("label", "Label")]
    if any(len(names) < len(datasets) for names in used.values()):
        columns.append(col("datasets", "Datasets"))
    rows = [
        {"code": code, "label": text, "datasets": ", ".join(names)}
        for (code, text), names in used.items()
    ]
    return columns, rows


def dataset_statistics(result: CatalogResult, instrument: Instrument, dataset: str) -> None:
    scores = {s.key: s for s in result.catalog.scores}
    summaries = [
        s
        for s in result.summary.scores
        if s.dataset == dataset and scores[s.key].instrument_id == instrument.id
    ]
    if summaries:
        heading("Scores")
        table(*score_table(result, summaries))
    heading("Items")
    table(*variable_table(result, instrument, dataset))
    items = item_ids(result, dataset)
    for summary in summaries:
        score = scores[summary.key]
        if summary.item_total:
            heading(f"{score.label}: item-total correlations (α {fmt(summary.alpha)})")
            table(
                [
                    col("column", "Variable"),
                    col("item", "Item"),
                    col("r", "Item-total r", numeric=True),
                    col("alpha_if_deleted", "α if deleted", numeric=True),
                ],
                [
                    {
                        "column": t.column,
                        "item": items.get(t.column, ""),
                        "r": fmt(t.r),
                        "alpha_if_deleted": fmt(t.alpha_if_deleted),
                    }
                    for t in summary.item_total
                ],
            ).classes(remove="w-full")
        heading(f"{score.label}: scoring code")
        snippets = result.snippets[summary.key]
        with ui.tabs().props("dense no-caps align=left") as tabs:
            ui.tab("r", label="R")
            ui.tab("python", label="Python")
        with ui.tab_panels(tabs, value="r").classes("w-full"):
            with ui.tab_panel("r").classes("p-0"):
                ui.code(snippets["r"], language="r").classes("w-full")
            with ui.tab_panel("python").classes("p-0"):
                ui.code(snippets["python"], language="python").classes("w-full")


def item_ids(result: CatalogResult, dataset: str) -> dict[str, str]:
    return {v.column: v.item_id for v in result.catalog.variables if v.dataset == dataset}


def score_table(result: CatalogResult, summaries: list) -> tuple[list[dict], list[dict]]:
    scores = {s.key: s for s in result.catalog.scores}
    columns = [
        col("score", "Score"),
        col("method", "Method"),
        col("n", "N", numeric=True),
        col("mean", "Mean", numeric=True),
        col("sd", "SD", numeric=True),
        col("median", "Median", numeric=True),
        col("observed", "Observed range"),
        col("possible", "Possible range"),
        col("alpha", "α", numeric=True),
        col("n_complete", "Answered all", numeric=True),
    ]
    rows = [
        {
            "score": scores[s.key].label,
            "method": f"{scores[s.key].method}, {scores[s.key].missing_rule}",
            "n": s.n_valid,
            "mean": fmt(s.mean),
            "sd": fmt(s.sd),
            "median": fmt(s.median),
            "observed": f"{fmt(s.minimum)} to {fmt(s.maximum)}" if s.n_valid else "",
            "possible": f"{fmt(s.possible_range[0])} to {fmt(s.possible_range[1])}",
            "alpha": fmt(s.alpha),
            "n_complete": s.n_complete,
        }
        for s in summaries
    ]
    return columns, rows


def variable_table(
    result: CatalogResult, instrument: Instrument, dataset: str
) -> tuple[list[dict], list[dict]]:
    columns_here = {
        v.column: v.item_id
        for v in result.catalog.variables
        if v.instrument_id == instrument.id and v.dataset == dataset
    }
    columns = [
        col("column", "Variable"),
        col("item", "Item"),
        col("n_valid", "Valid", numeric=True),
        col("missing", "Missing", sortable=False),
        col("n_unexpected", "Not an option", numeric=True),
        col("mean", "Mean", numeric=True),
        col("sd", "SD", numeric=True),
        col("responses", "Responses", sortable=False),
    ]
    rows = [
        {
            "column": v.column,
            "item": columns_here[v.column],
            "n_valid": v.n_valid,
            "missing": ", ".join(f"{label} {n}" for label, n in v.missing.items() if n),
            "n_unexpected": v.n_unexpected or "",
            "mean": fmt(v.mean),
            "sd": fmt(v.sd),
            "responses": ", ".join(f"{value}: {n}" for value, n in v.value_counts.items()),
        }
        for v in result.summary.variables
        if v.dataset == dataset and v.column in columns_here
    ]
    return columns, rows
