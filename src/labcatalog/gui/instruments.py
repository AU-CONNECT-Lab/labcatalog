from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from nicegui import app, run, ui

from labcatalog import ai_scoring
from labcatalog.browse import BrowseIndex, counts, matches
from labcatalog.cfa import SUBSCALES, CfaFit
from labcatalog.charts import views
from labcatalog.config import dataset_by_name, missing_codes_for
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import charts, preferences
from labcatalog.gui.common import (
    as_text,
    col,
    fmt,
    heading,
    note,
    open_path,
    section,
    table,
    unique,
)
from labcatalog.history import file_history
from labcatalog.invariance import STEPS, InvarianceTest
from labcatalog.pipeline import CatalogResult, run_scoring_script
from labcatalog.project import Project, reference_pdf
from labcatalog.resolve import as_text_dict
from labcatalog.schema import Instrument, Reference, Text
from labcatalog.stats import VariableSummary

PAGE_SIZE = 50
CFA_UNSET = "unset"
CFA_RUNNING = "running"
CFA_DONE = "done"
CFA_FAILED = "failed"


@dataclass
class BrowseView:
    selected: dict[str, set[str]] = field(default_factory=dict)
    query: str = ""
    items: bool = False
    instrument: str | None = None


@dataclass
class CfaView:
    # One object per window, changed in place so tables drawn earlier see the new state.
    status: str = CFA_UNSET
    fits: list[CfaFit] = field(default_factory=list)
    message: str = ""
    # Invariance runs after the CFA, so it has its own status.
    invariance_status: str = CFA_UNSET
    invariance: list[InvarianceTest] = field(default_factory=list)
    invariance_message: str = ""


def render(
    result: CatalogResult,
    index: BrowseIndex,
    view: BrowseView,
    on_open: Callable[[str | None], None],
    cfa: CfaView,
) -> None:
    if view.instrument not in result.project.instruments:
        browser(result, index, view, on_open)
        return
    found = matches(index, view.selected, view.query, view.items)
    ui.button("All instruments", icon="arrow_back", on_click=lambda: on_open(None)).props(
        "flat dense no-caps"
    )
    detail(result, result.project.instruments[view.instrument], found.get(view.instrument, []), cfa)
    history(result.project, view.instrument)


def browser(
    result: CatalogResult,
    index: BrowseIndex,
    view: BrowseView,
    on_open: Callable[[str | None], None],
) -> None:
    @ui.refreshable
    def facets() -> None:
        facet_panel(index, view, changed)

    @ui.refreshable
    def results() -> None:
        found = matches(index, view.selected, view.query, view.items)
        note(f"{len(found)} of {len(index.instruments)} instruments")
        shown = table(*list_table(result, found), pagination=PAGE_SIZE)
        shown.classes("cursor-pointer")
        shown.on("rowClick", lambda e: on_open(e.args[1]["id"]))

    def changed() -> None:
        facets.refresh()
        results.refresh()

    def set_query(value: str | None) -> None:
        view.query = value or ""
        changed()

    def set_items(value: bool) -> None:
        view.items = value
        changed()

    def clear() -> None:
        view.selected.clear()
        changed()

    with ui.row().classes("w-full no-wrap items-start gap-6"):
        with ui.column().classes("w-60 shrink-0 gap-1"):
            ui.input(
                placeholder="Search", value=view.query, on_change=lambda e: set_query(e.value)
            ).props("dense outlined clearable").classes("w-full")
            ui.checkbox(
                "Also search item text", value=view.items, on_change=lambda e: set_items(e.value)
            ).props("dense")
            facets()
            ui.button("Clear filters", on_click=clear).props("flat dense no-caps")
        with ui.column().classes("grow min-w-0"):
            results()


def facet_panel(index: BrowseIndex, view: BrowseView, changed: Callable[[], None]) -> None:
    def toggle(chosen: set[str], value: str, on: bool) -> None:
        if on:
            chosen.add(value)
        else:
            chosen.discard(value)
        changed()

    found = counts(index, view.selected, view.query, view.items)
    for facet in index.facets:
        # A facet with one value cannot narrow anything.
        if len(facet.values) < 2:
            continue
        chosen = view.selected.setdefault(facet.name, set())
        ui.label(facet.label).classes("font-medium mt-3")
        for value, label in facet.values.items():
            n = found[facet.name][value]
            if n or value in chosen:
                ui.checkbox(
                    f"{label} ({n})",
                    value=value in chosen,
                    on_change=lambda e, c=chosen, v=value: toggle(c, v, e.value),
                ).props("dense")


def list_table(result: CatalogResult, found: dict[str, list[str]]) -> tuple[list[dict], list[dict]]:
    config = result.project.config
    hit = {name for names in found.values() for name in names}
    datasets = [d.name for d in config.datasets if d.name in hit]
    answered = {
        (c.instrument_id, d.dataset): c.complete + c.partial
        for d in result.summary.datasets
        for c in d.completeness
    }
    who = {(v.instrument_id, v.dataset): (v.reporter, v.target) for v in result.catalog.variables}
    columns = [
        col("abbreviation", "Abbr."),
        col("name", "Name"),
        col("construct", "Construct"),
        col("reporters", "Reporter"),
        col("targets", "About"),
        col("items", "Items", numeric=True),
        *[col(f"d{i}", name, numeric=True) for i, name in enumerate(datasets)],
    ]
    rows = []
    for instrument_id, names in found.items():
        instrument = result.project.instruments[instrument_id]
        pairs = [who[(instrument_id, name)] for name in names if (instrument_id, name) in who]
        rows.append(
            {
                "id": instrument_id,
                "abbreviation": instrument.abbreviation or "",
                "name": instrument.name,
                "construct": instrument.construct_name or "",
                "reporters": ", ".join(unique(reporter for reporter, _ in pairs)),
                "targets": ", ".join(unique(target for _, target in pairs if target)),
                "items": len(instrument.items),
                **{
                    f"d{i}": answered.get((instrument_id, name), "") if name in names else ""
                    for i, name in enumerate(datasets)
                },
            }
        )
    return columns, rows


def detail(
    result: CatalogResult, instrument: Instrument, preferred: list[str], cfa: CfaView
) -> None:
    about(result, instrument)
    definition(result, instrument)
    datasets = administered_in(result, instrument.id)
    if not datasets:
        return
    if any(s.instrument_id == instrument.id for s in result.catalog.scores):
        scores_part(result, instrument, cfa)
    items_part(result, instrument)
    dataset_part(result, instrument, datasets, preferred, cfa)


def definition(result: CatalogResult, instrument: Instrument) -> None:
    section("Items")
    with ui.row().classes("w-full gap-6 items-start"):
        with ui.column().classes("gap-1 min-w-0").style("flex: 1 1 480px"):
            table(*item_table(result, instrument))
        with ui.column().classes("gap-1"):
            for response_set in instrument.response_sets:
                heading(f"Options: {response_set.id}")
                table(
                    [col("value", "Value", numeric=True), col("label", "Label")],
                    [o.model_dump() for o in response_set.options],
                ).classes(remove="w-full")
            heading("Missing codes")
            table(*missing_code_table(result, instrument)).classes(remove="w-full")


def scores_part(result: CatalogResult, instrument: Instrument, cfa: CfaView) -> None:
    section("Scores")
    score_statistics(result, instrument, cfa)
    charts.score_charts(result, instrument.id)
    stable = stability_table(result, instrument)
    if stable is not None:
        heading("Stability across waves")
        note("r between the same people's scores one wave apart (n people).")
        table(*stable).classes(remove="w-full")
        invariance_section(result, instrument, cfa)
    charts.other_scores(result, instrument.id)


def items_part(result: CatalogResult, instrument: Instrument) -> None:
    section("Item analysis")
    if instrument.kind == "demographics":
        heading("Sample by wave")
        table(*sample_table(result, instrument))
    charts.item_charts(result, instrument.id)
    item_totals(result, instrument)
    charts.item_correlation_section(result, instrument.id)


def dataset_part(
    result: CatalogResult,
    instrument: Instrument,
    datasets: list[str],
    preferred: list[str],
    cfa: CfaView,
) -> None:
    first = next((d for d in preferred if d in datasets), datasets[0])

    @ui.refreshable
    def one_dataset(dataset: str) -> None:
        heading(f"Items in {dataset}")
        table(*variable_table(result, instrument, dataset))
        factor_structure(result, instrument, dataset, cfa)
        charts.instrument_dataset_section(result, instrument.id, dataset)
        scoring_code(result, instrument, dataset)

    section("One dataset")
    ui.toggle(datasets, value=first, on_change=lambda e: one_dataset.refresh(e.value)).props(
        "dense no-caps"
    ).classes("mt-4")
    one_dataset(first)


def item_totals(result: CatalogResult, instrument: Instrument) -> None:
    choices = {
        s.id: s.label
        for s in instrument.scores
        if any(
            views.summary_of(result, r.key).item_total
            for r in views.resolved(result, instrument.id, s.id)
        )
    }
    if not choices:
        return
    total = views.total_score(instrument)
    first = total.id if total is not None and total.id in choices else next(iter(choices))

    @ui.refreshable
    def body(score_id: str) -> None:
        table(*item_total_waves(result, instrument, score_id)).classes(remove="w-full")

    heading("Item-total correlations")
    if len(choices) > 1:
        ui.select(
            choices, value=first, label="Score", on_change=lambda e: body.refresh(e.value)
        ).props("dense outlined").classes("w-72")
    body(first)
    note("r of each item with the sum of the other items; α without the item in brackets.")


def history(project: Project, instrument_id: str) -> None:
    path = project.instrument_files[instrument_id]
    changes = file_history(project.root, path)
    if changes is None:
        return
    section("History")
    if not changes:
        note(f"No commits include {path} yet.")
        return
    note(f"Changes to {path} recorded in git; open one to see what changed.")
    for change in changes:
        caption = f"{change.date}, {change.author}" if change.commit else None
        with ui.expansion(change.message, caption=caption).classes("w-full"):
            ui.code(change.diff, language="diff").classes("w-full")


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
        reference_row(result.project, reference)
    if instrument.license:
        note(f"License: {instrument.license}")


def reference_row(project: Project, reference: Reference) -> None:
    pdf = reference_pdf(project, reference.pdf) if reference.pdf else None
    with ui.row().classes("items-baseline gap-2"):
        ui.label(reference.citation)
        if reference.doi:
            ui.link("DOI", f"https://doi.org/{reference.doi}", new_tab=True)
        if reference.url:
            ui.link("Link", reference.url, new_tab=True)
        if pdf and pdf.is_file():
            ui.button("View PDF", on_click=lambda: toggle_viewer()).props("flat dense no-caps")
            ui.button("Open", on_click=lambda: open_path(pdf)).props("flat dense no-caps")
        elif pdf:
            note("PDF not found")
    viewer = ui.column().classes("w-full")

    # The PDF loads only when someone asks to see it.
    def toggle_viewer() -> None:
        if viewer.default_slot.children:
            viewer.clear()
            return
        with viewer:
            ui.element("iframe").props(f'src="{pdf_url(pdf)}"').classes("w-full").style(
                "height: 80vh; border: 1px solid #e0e0e0"
            )


# One route per file, however often the page is redrawn.
@cache
def pdf_url(pdf: Path) -> str:
    return app.add_static_file(local_file=pdf, max_cache_age=0)


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
            "options": (item.response_set or instrument.default_response_set or "")
            if item.type == "choice"
            else item.type,
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


def score_summaries(result: CatalogResult, instrument: Instrument, dataset: str) -> list:
    scores = {s.key: s for s in result.catalog.scores}
    return [
        s
        for s in result.summary.scores
        if s.dataset == dataset and scores[s.key].instrument_id == instrument.id
    ]


def cfa_changed() -> None:
    score_statistics.refresh()
    factor_structure.refresh()
    invariance_section.refresh()


# Module level, so a finished CFA can redraw this table without redrawing the page.
@ui.refreshable
def score_statistics(result: CatalogResult, instrument: Instrument, cfa: CfaView) -> None:
    table(*score_table(result, instrument, cfa.fits))


def scoring_code(result: CatalogResult, instrument: Instrument, dataset: str) -> None:
    snippets = result.snippets.get((instrument.id, dataset))
    if snippets is not None:
        heading(f"Scoring code for {dataset}")
        code_tabs(snippets)
    written_scripts(result, instrument, dataset)


def code_tabs(code: dict[str, str]) -> None:
    with ui.tabs().props("dense no-caps align=left") as tabs:
        ui.tab("r", label="R")
        ui.tab("python", label="Python")
    with ui.tab_panels(tabs, value="r").classes("w-full"):
        with ui.tab_panel("r").classes("p-0"):
            ui.code(code["r"], language="r").classes("w-full")
        with ui.tab_panel("python").classes("p-0"):
            ui.code(code["python"], language="python").classes("w-full")


def written_scripts(result: CatalogResult, instrument: Instrument, dataset: str) -> None:
    if not ai_scoring.reference_pdfs(result.project, instrument):
        return
    paths = ai_scoring.script_paths(result.project, instrument.id, dataset)

    @ui.refreshable
    def saved() -> None:
        if paths["r"].is_file():
            note(f"Saved as {paths['r'].name} and {paths['python'].name} in {paths['r'].parent}.")
            code_tabs({k: path.read_text(encoding="utf-8") for k, path in paths.items()})

    async def write() -> None:
        button.disable()
        status.set_text("Reading the reference and writing the scripts.")
        chosen = preferences.load()
        try:
            meta = await run.io_bound(
                run_scoring_script,
                result,
                instrument.id,
                dataset,
                chosen.get(preferences.LLM_PROVIDER, preferences.DEFAULT_LLM_PROVIDER),
                chosen.get(preferences.LLM_MODEL, ""),
                chosen.get(preferences.LLM_URL, ""),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
        else:
            status.set_text(
                f"Written by {meta.model} in {meta.latency_ms / 1000:.0f} s, "
                f"{meta.input_tokens} tokens in and {meta.output_tokens} out."
            )
            saved.refresh()
        finally:
            button.enable()

    heading(f"Scoring script from the reference PDF for {dataset}")
    with ui.row().classes("items-center gap-3"):
        button = ui.button("Write with the language model", on_click=write)
        status = ui.label().classes("lc-note")
    saved()


def item_total_waves(
    result: CatalogResult, instrument: Instrument, score_id: str
) -> tuple[list[dict], list[dict]]:
    score = next(s for s in instrument.scores if s.id == score_id)
    summaries = [
        views.summary_of(result, s.key) for s in views.resolved(result, instrument.id, score_id)
    ]
    summaries = [s for s in summaries if s.item_total]
    names = views.series_names(result, [s.dataset for s in summaries])
    columns = [
        col("n", "#", numeric=True),
        col("item", "Item"),
        *[
            col(f"d{i}", f"{names[s.dataset]} (α {fmt(s.alpha)})", numeric=True)
            for i, s in enumerate(summaries)
        ],
    ]
    found = [
        {item_ids(result, s.dataset).get(t.column): t for t in s.item_total} for s in summaries
    ]
    numbers = {item.id: n for n, item in enumerate(instrument.items, start=1)}
    rows = [
        {
            "n": numbers[item],
            "item": item,
            **{
                f"d{i}": f"{fmt(t.r)} ({fmt(t.alpha_if_deleted)})"
                if (t := values.get(item))
                else ""
                for i, values in enumerate(found)
            },
        }
        for item in score.items
    ]
    return columns, rows


def stability_table(
    result: CatalogResult, instrument: Instrument
) -> tuple[list[dict], list[dict]] | None:
    rows_found = [s for s in result.summary.stability if s.instrument_id == instrument.id]
    if not rows_found:
        return None
    pairs = list(dict.fromkeys((s.study, s.from_wave, s.to_wave) for s in rows_found))
    reporters = unique(s.reporter for s in rows_found)
    cells = {(s.score_id, s.reporter, s.study, s.from_wave, s.to_wave): s for s in rows_found}
    columns = [
        col("score", "Score"),
        *[
            col(
                f"p{i}",
                f"{views.wave_name(result, study, a)} → {views.wave_name(result, study, b)}",
                numeric=True,
            )
            for i, (study, a, b) in enumerate(pairs)
        ],
    ]
    rows = []
    for score in instrument.scores:
        for reporter in reporters:
            found = [cells.get((score.id, reporter, *pair)) for pair in pairs]
            if not any(found):
                continue
            rows.append(
                {
                    "score": score.label if len(reporters) == 1 else f"{score.label} ({reporter})",
                    **{
                        f"p{i}": f"{fmt(s.r)} (n {s.n})" if s and s.r is not None else ""
                        for i, s in enumerate(found)
                    },
                }
            )
    return columns, rows


def item_ids(result: CatalogResult, dataset: str) -> dict[str, str]:
    return {v.column: v.item_id for v in result.catalog.variables if v.dataset == dataset}


@ui.refreshable
def factor_structure(
    result: CatalogResult, instrument: Instrument, dataset: str, cfa: CfaView
) -> None:
    if not score_summaries(result, instrument, dataset):
        return
    fits = [f for f in cfa.fits if (f.instrument_id, f.dataset) == (instrument.id, dataset)]
    heading(f"Factor structure in {dataset}")
    if cfa.status == CFA_UNSET:
        note("Set the path to Rscript on the Settings page to fit factor models (CFA) and get ω.")
    elif cfa.status == CFA_RUNNING:
        note("Fitting factor models in R.")
    elif cfa.status == CFA_FAILED:
        note(cfa.message)
    elif not fits:
        note("No factor model: no score here has three or more items.")
    else:
        note(
            "lavaan, WLSMV with the items as ordered categories, people who answered every "
            "item; standardized loadings; ω is semTools' categorical omega."
        )
        table(*fit_table(instrument, fits))
        table(*loading_table(result, instrument, dataset, fits)).classes(remove="w-full")


def omegas(fits: list[CfaFit]) -> dict[str, float]:
    return {score: value for f in fits for score, value in f.omega.items()}


def fit_table(instrument: Instrument, fits: list[CfaFit]) -> tuple[list[dict], list[dict]]:
    labels = {s.id: s.label for s in instrument.scores}
    columns = [
        col("model", "Model"),
        col("n", "N", numeric=True),
        col("chisq", "χ² (df)", numeric=True),
        col("p", "p", numeric=True),
        col("cfi", "CFI", numeric=True),
        col("tli", "TLI", numeric=True),
        col("rmsea", "RMSEA", numeric=True),
        col("srmr", "SRMR", numeric=True),
        col("problem", "Note", sortable=False),
    ]
    rows = []
    for f in fits:
        names = ", ".join(labels[s] for s in f.factors)
        model = f"Subscales: {names}" if f.kind == SUBSCALES else f"One factor: {names}"
        values = f.fit
        exact = not f.problem and values.get("df") == 0
        rows.append(
            {
                "model": model,
                "n": f.n,
                "chisq": f"{fmt(values['chisq'])} ({values['df']:g})"
                if values.get("chisq") is not None
                else "",
                "p": fmt(values.get("p"), 3),
                **{key: fmt(values.get(key)) for key in ("cfi", "tli", "rmsea", "srmr")},
                "problem": f.problem
                or ("3 items: the model fits exactly, so it has no fit indices" if exact else ""),
            }
        )
    return columns, rows


def loading_table(
    result: CatalogResult, instrument: Instrument, dataset: str, fits: list[CfaFit]
) -> tuple[list[dict], list[dict]]:
    used = {score for f in fits for score in f.factors}
    scores = [s for s in instrument.scores if s.id in used]
    loadings = {key: value for f in fits for key, value in f.loadings.items()}
    modelled = {column for f in fits for columns in f.factors.values() for column in columns}
    variables = [
        v
        for v in result.catalog.variables_for(dataset)
        if v.instrument_id == instrument.id and v.column in modelled
    ]
    columns = [
        col("column", "Variable"),
        col("item", "Item"),
        *[col(f"s_{s.id}", s.label, numeric=True) for s in scores],
    ]
    rows = [
        {
            "column": v.column,
            "item": v.item_id,
            **{f"s_{s.id}": fmt(loadings.get((s.id, v.column))) for s in scores},
        }
        for v in variables
    ]
    found = omegas(fits)
    rows.append({"column": "ω", "item": "", **{f"s_{s.id}": fmt(found.get(s.id)) for s in scores}})
    return columns, rows


@ui.refreshable
def invariance_section(result: CatalogResult, instrument: Instrument, cfa: CfaView) -> None:
    tests = [t for t in cfa.invariance if t.instrument_id == instrument.id]
    heading("Invariance across waves")
    if cfa.invariance_status == CFA_UNSET:
        note("Set the path to Rscript on the Settings page to test invariance across waves.")
    elif cfa.invariance_status == CFA_RUNNING:
        note("Testing invariance across waves in R.")
    elif cfa.invariance_status == CFA_FAILED:
        note(cfa.invariance_message)
    elif not tests:
        note("No model: no score here has three or more items in two or more waves.")
    else:
        note(
            "lavaan and semTools: each wave's items load on their own factors, the same people "
            "are linked by ID, and each item's residuals correlate across waves; WLSMV with the "
            "items as ordered categories, people who answered every item at a wave. Each step "
            "holds one more set of parameters equal across waves; Δχ² is the scaled difference "
            "test against the step before. A drop in CFI of more than 0.01 is a common sign "
            "that a step does not hold."
        )
        labels = {s.id: s.label for s in instrument.scores}
        for test in tests:
            names = ", ".join(labels[s] for s in test.factors)
            kind = "Subscales" if test.kind == SUBSCALES else "One factor"
            waves = ", ".join(
                f"{views.wave_name(result, test.study, wave)} {n}" for wave, n in test.n.items()
            )
            ui.label(f"{kind}: {names}").classes("font-medium mt-2")
            note(f"{test.reporter} in {test.study}; people per wave: {waves}.")
            if test.problem:
                note(test.problem)
            else:
                table(*invariance_table(test)).classes(remove="w-full")


def invariance_table(test: InvarianceTest) -> tuple[list[dict], list[dict]]:
    names = {
        "configural": "Configural",
        "thresholds": "Thresholds",
        "metric": "Metric (+ loadings)",
        "scalar": "Scalar (+ intercepts)",
    }
    columns = [
        col("step", "Step"),
        col("chisq", "χ² (df)", numeric=True),
        col("cfi", "CFI", numeric=True),
        col("rmsea", "RMSEA", numeric=True),
        col("srmr", "SRMR", numeric=True),
        col("diff", "Δχ² (Δdf)", numeric=True),
        col("p", "p", numeric=True),
        col("dcfi", "ΔCFI", numeric=True),
        col("drmsea", "ΔRMSEA", numeric=True),
        col("problem", "Note", sortable=False),
    ]
    rows = []
    previous = None
    for step in sorted(test.steps, key=lambda s: STEPS.index(s.step)):
        values = step.fit
        before = previous.fit if previous and not previous.problem else {}
        rows.append(
            {
                "step": names[step.step],
                "chisq": f"{fmt(values['chisq'])} ({values['df']:g})" if values else "",
                **{key: fmt(values.get(key), 3) for key in ("cfi", "rmsea", "srmr")},
                "diff": f"{fmt(step.chisq_diff)} ({step.df_diff:g})"
                if step.chisq_diff is not None
                else "",
                "p": fmt(step.p_diff, 3),
                **{
                    f"d{key}": fmt(values[key] - before[key], 3)
                    if values.get(key) is not None and before.get(key) is not None
                    else ""
                    for key in ("cfi", "rmsea")
                },
                "problem": step.problem or "",
            }
        )
        previous = step
    return columns, rows


def score_table(
    result: CatalogResult, instrument: Instrument, fits: list[CfaFit]
) -> tuple[list[dict], list[dict]]:
    # One row per score and wave; what belongs to the score itself sits on its first row only.
    omega = {
        (f.dataset, score): value
        for f in fits
        if f.instrument_id == instrument.id
        for score, value in f.omega.items()
    }
    fields = [
        f
        for f in result.project.config.custom_fields
        if f.applies_to == "score" and any(f.name in s.custom for s in instrument.scores)
    ]
    names = views.series_names(result, views.instrument_datasets(result, instrument.id))
    columns = [
        col("score", "Score"),
        *[col(f"custom_{f.name}", f.label or f.name.capitalize()) for f in fields],
        col("method", "Method"),
        col("wave", "Wave"),
        col("n", "N", numeric=True),
        col("mean", "Mean", numeric=True),
        col("sd", "SD", numeric=True),
        col("median", "Median", numeric=True),
        col("observed", "Observed range"),
        col("possible", "Possible range"),
        col("alpha", "α", numeric=True),
        *([col("omega", "ω", numeric=True)] if omega else []),
        col("n_complete", "Answered all", numeric=True),
    ]
    rows = []
    for score in instrument.scores:
        for k, s in enumerate(views.resolved(result, instrument.id, score.id)):
            summary = views.summary_of(result, s.key)
            own = {
                "score": score.label,
                **{f"custom_{f.name}": as_text(score.custom.get(f.name)) for f in fields},
                "method": f"{s.method}, {s.missing_rule}",
            }
            rows.append(
                {
                    **(own if k == 0 else dict.fromkeys(own, "")),
                    "wave": names[s.dataset],
                    "n": summary.n_valid,
                    "mean": fmt(summary.mean),
                    "sd": fmt(summary.sd),
                    "median": fmt(summary.median),
                    "observed": f"{fmt(summary.minimum)} to {fmt(summary.maximum)}"
                    if summary.n_valid
                    else "",
                    "possible": f"{fmt(summary.possible_range[0])} to "
                    f"{fmt(summary.possible_range[1])}",
                    "alpha": fmt(summary.alpha),
                    "omega": fmt(omega.get((s.dataset, score.id))),
                    "n_complete": summary.n_complete,
                }
            )
    # Sorting would pull a score's rows apart.
    return [{**c, "sortable": False} for c in columns], rows


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
            "responses": responses_text(v),
        }
        for v in result.summary.variables
        if v.dataset == dataset and v.column in columns_here
    ]
    return columns, rows


def responses_text(summary: VariableSummary) -> str:
    if summary.median is not None:
        return f"median {summary.median:g}, range {summary.minimum:g} to {summary.maximum:g}"
    return ", ".join(f"{value}: {n}" for value, n in summary.value_counts.items())


def sample_table(result: CatalogResult, instrument: Instrument) -> tuple[list[dict], list[dict]]:
    datasets = administered_in(result, instrument.id)
    columns_by_item = {
        (v.item_id, v.dataset): v.column
        for v in result.catalog.variables
        if v.instrument_id == instrument.id
    }
    summaries = {(v.dataset, v.column): v for v in result.summary.variables}
    sets = {response_set.id: response_set for response_set in instrument.response_sets}
    columns = [
        col("item", "Item", sortable=False),
        col("value", "", sortable=False),
        *[col(f"d{i}", name, numeric=True, sortable=False) for i, name in enumerate(datasets)],
    ]
    rows = []
    for item in instrument.items:
        cells: list[tuple[str, Callable[[VariableSummary], str | int]]] = [
            ("Answered" if item.type == "text" else "n", lambda s: s.n_valid)
        ]
        if item.type == "choice":
            options = sets[item.response_set or instrument.default_response_set].options
            cells += [(o.label, lambda s, v=str(o.value): share(s, v)) for o in options]
        elif item.type == "number":
            cells += [
                ("Mean (SD)", lambda s: f"{fmt(s.mean, 1)} ({fmt(s.sd, 1)})"),
                ("Median", lambda s: fmt(s.median, 1)),
                ("Range", lambda s: f"{fmt(s.minimum, 1)} to {fmt(s.maximum, 1)}"),
            ]
        for n, (label, cell) in enumerate(cells):
            row = {"item": text_of(item.text) if n == 0 else "", "value": label}
            for i, name in enumerate(datasets):
                column = columns_by_item.get((item.id, name))
                row[f"d{i}"] = cell(summaries[(name, column)]) if column else ""
            rows.append(row)
    return columns, rows


def share(summary: VariableSummary, value: str) -> str:
    n = summary.value_counts.get(value, 0)
    return f"{n} ({n / summary.n_valid:.0%})" if summary.n_valid else str(n)
