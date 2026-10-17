from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from nicegui import app, ui

from labcatalog.ai import scoring as ai_scoring
from labcatalog.ai.search import Search
from labcatalog.charts import views
from labcatalog.config import dataset_by_name, missing_codes_for
from labcatalog.data.resolve import as_text_dict
from labcatalog.datalad.annex import is_placeholder
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import charts, new_instrument, preferences
from labcatalog.gui import invariance as invariance_view
from labcatalog.gui.common import (
    as_text,
    cited,
    code_tabs,
    col,
    computed,
    fmt,
    note,
    open_path,
    p_value,
    panel,
    table,
    unique,
)
from labcatalog.gui.datalad import get_button
from labcatalog.gui.paper import copy_text, paper_table, save_button, without_empty
from labcatalog.metadata.browse import BrowseIndex, counts, matches
from labcatalog.metadata.completeness import gaps
from labcatalog.metadata.history import Change, file_history
from labcatalog.paths import portable_path
from labcatalog.pipeline import (
    CatalogResult,
    run_description_draft,
    run_get,
    run_scoring_script,
    run_search,
)
from labcatalog.project import Project, reference_pdf
from labcatalog.reports import measures
from labcatalog.reports.export import (
    BY_DATASET,
    BY_GROUP,
    BY_ID,
    ITEM_STATISTICS,
    SCORE_STATISTICS,
    VARIABLES,
    export_plan,
    layouts,
    named_plan,
    write_export,
)
from labcatalog.reports.tables import PaperTable
from labcatalog.schema import Instrument, Reference, Text
from labcatalog.stats.cfa import SUBSCALES, WLSMV, CfaFit, R
from labcatalog.stats.invariance import (
    REPORTERS,
    WAVES,
    InvarianceModel,
    InvarianceTest,
    build_models,
)
from labcatalog.stats.summary import VariableSummary

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
    # The tab open on an instrument's page, kept when another instrument opens.
    part: str = "items"
    # Instruments ticked for export, kept across filters and refreshes.
    chosen: set[str] = field(default_factory=set)
    asked: Search | None = None

    @property
    def only(self) -> set[str] | None:
        return self.asked.instruments if self.asked else None


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
    open_settings: Callable[[], None] | None = None
    # Reloads the project, after a change to labcatalog.yaml.
    reload: Callable[[], Awaitable[None]] | None = None


def render(
    result: CatalogResult,
    index: BrowseIndex,
    view: BrowseView,
    on_open: Callable[[str | None], None],
    cfa: CfaView,
) -> None:
    if view.instrument not in result.project.instruments:
        browser(result, index, view, on_open, cfa)
        return
    found = matches(index, view.selected, view.query, view.items, view.only)
    instrument = result.project.instruments[view.instrument]
    with ui.row().classes("items-center gap-1 no-wrap"):
        ui.button("Instruments", icon="arrow_back", on_click=lambda: on_open(None)).props(
            "flat dense no-caps"
        )
        ui.icon("chevron_right").classes("lc-crumb-sep")
        ui.label(instrument.abbreviation or instrument.name).classes("lc-crumb")
    detail(result, instrument, found.get(view.instrument, []), cfa, view)


def browser(
    result: CatalogResult,
    index: BrowseIndex,
    view: BrowseView,
    on_open: Callable[[str | None], None],
    cfa: CfaView,
) -> None:
    @ui.refreshable
    def facets() -> None:
        facet_panel(index, view, changed)

    @ui.refreshable
    def results() -> None:
        found = matches(index, view.selected, view.query, view.items, view.only)

        @ui.refreshable
        def chosen_bar() -> None:
            ui.label(f"{len(view.chosen)} chosen").classes("lc-note")
            ui.button(
                "Export", icon="download", on_click=lambda: export_dialog(result, found, view, cfa)
            ).props("flat dense no-caps").classes("lc-quiet-btn").set_enabled(bool(view.chosen))

        def choose(selection: list[dict]) -> None:
            # Instruments the filters hide stay chosen.
            here = {row["id"] for row in shown.rows}
            view.chosen = (view.chosen - here) | {row["id"] for row in selection}
            chosen_bar.refresh()

        with panel("Instruments", f"{len(found)} of {len(index.instruments)} shown") as tools:
            with tools:
                chosen_bar()
                ui.button(
                    "Add an instrument",
                    icon="add",
                    on_click=lambda: new_instrument.open_wizard(result, wizard_done(view, cfa)),
                ).props("flat dense no-caps").classes("lc-quiet-btn")
            shown = table(*list_table(result, found), pagination=PAGE_SIZE)
        shown.set_selection("multiple")
        shown.selected = [row for row in shown.rows if row["id"] in view.chosen]
        shown.on_select(lambda e: choose(e.selection))
        shown.add_slot("body-cell-missing", MISSING_CELL)
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

    with ui.row().classes("w-full no-wrap items-start gap-4"):
        with ui.column().classes("w-64 shrink-0"), panel("Filters") as tools:
            with tools:
                ui.button("Clear", on_click=clear).props("flat dense no-caps")
            ui.input(
                placeholder="Search", value=view.query, on_change=lambda e: set_query(e.value)
            ).props("dense outlined clearable").classes("w-full")
            ui.checkbox(
                "Also search item text", value=view.items, on_change=lambda e: set_items(e.value)
            ).props("dense")
            facets()
        with ui.column().classes("grow min-w-0 gap-4"):
            ask_panel(result, view, changed, on_open)
            results()


def wizard_done(view: BrowseView, cfa: CfaView) -> Callable[[str], Awaitable[None]]:
    async def done(instrument_id: str) -> None:
        ui.notify(f"Saved {instrument_id}")
        view.instrument = instrument_id
        await cfa.reload()

    return done


def ask_panel(
    result: CatalogResult,
    view: BrowseView,
    changed: Callable[[], None],
    on_open: Callable[[str | None], None],
) -> None:
    @ui.refreshable
    def answer() -> None:
        if view.asked is None:
            return
        asked = view.asked
        if not asked.matches:
            note("The model found nothing that fits.")
        for instrument_id in unique(m.instrument_id for m in asked.matches):
            instrument = result.project.instruments[instrument_id]
            items = {item.id: item for item in instrument.items}
            ui.button(instrument.name, on_click=lambda i=instrument_id: on_open(i)).props(
                "flat dense no-caps"
            ).classes("font-medium -ml-2")
            for found in asked.matches:
                if found.instrument_id != instrument_id:
                    continue
                with ui.column().classes("gap-0 ml-4 mb-1"):
                    if found.item_id:
                        ui.label(f"{found.item_id}: {as_text(items[found.item_id].text)}")
                    note(found.reason)
        if asked.dropped:
            note(f"Left out {asked.dropped} of the model's matches: not in the catalog.")
        note("The list below shows only these instruments; Clear shows them all again.")

    async def ask() -> None:
        query = (box.value or "").strip()
        if not query:
            return
        button.disable()
        status.set_text("Asking the language model.")
        chosen = preferences.load()
        try:
            asked = await computed(
                run_search,
                result,
                query,
                chosen.get(preferences.LLM_PROVIDER, preferences.DEFAULT_LLM_PROVIDER),
                chosen.get(preferences.LLM_MODEL, ""),
                chosen.get(preferences.LLM_URL, ""),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
        else:
            meta = asked.meta
            status.set_text(
                f"Answered by {meta.model} in {meta.latency_ms / 1000:.0f} s, "
                f"{meta.input_tokens} tokens in and {meta.output_tokens} out."
            )
            view.asked = asked
            answer.refresh()
            changed()
        finally:
            button.enable()

    def clear() -> None:
        view.asked = None
        box.value = ""
        status.set_text("")
        answer.refresh()
        changed()

    with ui.expansion(
        "Ask the language model", icon="manage_search", value=bool(view.asked)
    ).classes("lc-panel lc-expansion w-full"):
        if not preferences.model_set():
            note("Set a language model on the Settings page to search the catalog with it.")
            return
        note(
            "Describe what you are looking for in your own words. Sends the instruments' names, "
            "labels and item texts, never any data, to the model set on the Settings page."
        )
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            box = (
                ui.input(
                    placeholder="e.g. trouble falling asleep",
                    value=view.asked.query if view.asked else "",
                )
                .props("dense outlined")
                .classes("grow")
            )
            box.on("keydown.enter", ask)
            button = ui.button("Ask", on_click=ask).props("no-caps")
            ui.button("Clear", on_click=clear).props("flat no-caps")
        status = ui.label().classes("lc-note")
        answer()


def export_dialog(
    result: CatalogResult, found: dict[str, list[str]], view: BrowseView, cfa: CfaView
) -> None:
    config = result.project.config
    names = {i: s.abbreviation or s.name for i, s in result.project.instruments.items()}
    # The datasets the filters show start ticked.
    shown = set(export_plan(result, found, view.chosen))
    state: dict = {"ticked": set(), "plan": {}}
    root = result.project.root
    group = config.ids.group
    labels = {
        BY_DATASET: "One file per dataset",
        BY_ID: "One table, a row per person (ID)",
        BY_GROUP: f"One table, a row per {group.name if group else 'group'}",
    }

    def chosen_ids() -> list[str]:
        return [i for i in result.project.instruments if i in (instruments.value or [])]

    def instruments_next() -> None:
        if not chosen_ids():
            ui.notify("Choose at least one instrument")
            return
        given = named_plan(result, chosen_ids(), [])
        state["ticked"] = {d for d in given if d in shown} or set(given)
        datasets_step.refresh()
        stepper.next()

    def tick(names_: list[str], on: bool) -> None:
        state["ticked"] = state["ticked"] | set(names_) if on else state["ticked"] - set(names_)
        datasets_step.refresh()

    @ui.refreshable
    def datasets_step() -> None:
        if not chosen_ids():
            return
        given = named_plan(result, chosen_ids(), [])
        ordered = views.dataset_order(result, list(given))
        waves = unique(
            (dataset_by_name(config, d).study, dataset_by_name(config, d).wave) for d in ordered
        )
        reporters = unique(dataset_by_name(config, d).reporter for d in ordered)
        cells: dict[tuple, list[str]] = {}
        for d in ordered:
            c = dataset_by_name(config, d)
            cells.setdefault((c.study, c.wave, c.reporter), []).append(d)
        ticked = state["ticked"]
        with ui.grid(columns=f"auto repeat({len(reporters)}, minmax(8rem, 1fr))").classes(
            "gap-x-6 gap-y-1 items-start"
        ):
            ui.label()
            for reporter in reporters:
                column = [d for d in ordered if dataset_by_name(config, d).reporter == reporter]
                ui.checkbox(
                    reporter,
                    value=set(column) <= ticked,
                    on_change=lambda e, c=column: tick(c, e.value),
                ).props("dense").classes("font-medium")
            for study, wave in waves:
                row = [
                    d
                    for d in ordered
                    if (dataset_by_name(config, d).study, dataset_by_name(config, d).wave)
                    == (study, wave)
                ]
                ui.checkbox(
                    views.wave_name(result, study, wave),
                    value=set(row) <= ticked,
                    on_change=lambda e, r=row: tick(r, e.value),
                ).props("dense").classes("font-medium")
                for reporter in reporters:
                    with ui.column().classes("gap-0"):
                        for d in cells.get((study, wave, reporter), []):
                            ui.checkbox(
                                d,
                                value=d in ticked,
                                on_change=lambda e, d=d: tick([d], e.value),
                            ).props("dense").tooltip(", ".join(names[i] for i in given[d]))
        missing = [names[i] for i in chosen_ids() if not any(i in given[d] for d in ticked)]
        if missing:
            note(f"No ticked dataset has {', '.join(missing)}.")

    def datasets_next() -> None:
        if not state["ticked"]:
            ui.notify("Tick at least one dataset")
            return
        state["plan"] = named_plan(result, chosen_ids(), sorted(state["ticked"]))
        format_step.refresh()
        saved.clear()
        export.set_visibility(True)
        opener.set_visibility(False)
        stepper.next()

    @ui.refreshable
    def format_step() -> None:
        plan = state["plan"]
        if not plan:
            return
        with ui.grid(columns="auto 1fr").classes("gap-x-4 gap-y-0"):
            for dataset, ids in plan.items():
                ui.label(dataset).classes("font-medium")
                ui.label(", ".join(names[i] for i in ids))
        state["layout"] = ui.radio(
            {key: labels[key] for key in layouts(result, plan)}, value=BY_DATASET
        ).props("dense")
        note(
            f"Writes a new folder in outputs/ with {VARIABLES}, which describes every variable, "
            "and the data: the ID and date columns, the chosen items as they are in the data and "
            f"the scores labcatalog computes; and the statistics: {SCORE_STATISTICS} and "
            f"{ITEM_STATISTICS} with each score's and item's n, mean, SD and range in each "
            "dataset. Open answers are listed but not exported. In one table, each column starts "
            "with its dataset's name."
        )

    async def go() -> None:
        done = await computed(write_export, result, state["plan"], state["layout"].value, cfa.fits)
        saved.clear()
        with saved:
            note(f"Saved to {portable_path(done.folder, root).as_posix()}")
            for name, n in done.left_out.items():
                note(f"Left out {n} rows of {name}: their key repeats in that file.")
        state["folder"] = done.folder
        export.set_visibility(False)
        opener.set_visibility(True)

    def navigation(on_next: Callable, back: bool = True) -> None:
        with ui.stepper_navigation():
            ui.button("Next", on_click=on_next)
            if back:
                ui.button("Back", on_click=stepper.previous).props("flat")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    with ui.dialog() as dialog, ui.card().classes("w-[48rem] max-w-full"):
        ui.label("Export").classes("text-lg font-medium")
        with ui.stepper().props("flat animated").classes("w-full") as stepper:
            with ui.step("Instruments"):
                note("The instruments whose items and scores go into the export.")
                instruments = (
                    ui.select(
                        {
                            i: f"{names[i]}: {s.name}" if s.abbreviation else s.name
                            for i, s in result.project.instruments.items()
                        },
                        value=[i for i in result.project.instruments if i in view.chosen],
                        label="Instruments",
                        multiple=True,
                    )
                    .props("use-chips")
                    .classes("w-full")
                )
                navigation(instruments_next, back=False)
            with ui.step("Datasets"):
                note(
                    "The datasets that give these instruments. Tick a wave or a reporter to take "
                    "all of its datasets."
                )
                datasets_step()
                navigation(datasets_next)
            with ui.step("Format"):
                format_step()
                saved = ui.column().classes("gap-0")
                with ui.stepper_navigation():
                    export = ui.button("Export", icon="download", on_click=go)
                    opener = ui.button(
                        "Open folder",
                        icon="folder_open",
                        on_click=lambda: open_path(state["folder"]),
                    )
                    opener.set_visibility(False)
                    ui.button("Back", on_click=stepper.previous).props("flat")
                    ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def facet_panel(index: BrowseIndex, view: BrowseView, changed: Callable[[], None]) -> None:
    def toggle(chosen: set[str], value: str, on: bool) -> None:
        if on:
            chosen.add(value)
        else:
            chosen.discard(value)
        changed()

    found = counts(index, view.selected, view.query, view.items, view.only)
    for facet in index.facets:
        # A facet with one value cannot narrow anything.
        if len(facet.values) < 2:
            continue
        chosen = view.selected.setdefault(facet.name, set())
        ui.label(facet.label).classes("lc-facet")
        for value, label in facet.values.items():
            n = found[facet.name][value]
            if n or value in chosen:
                ui.checkbox(
                    f"{label} ({n})",
                    value=value in chosen,
                    on_change=lambda e, c=chosen, v=value: toggle(c, v, e.value),
                ).props("dense")


MISSING_CELL = r"""
<q-td :props="props">
  <span v-for="gap in props.value ? props.value.split(', ') : []" :key="gap"
        class="lc-pill lc-warn q-mr-xs">{{ gap }}</span>
</q-td>
"""


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
        {**col("name", "Name"), "style": "min-width: 13rem"},
        {**col("construct", "Construct"), "style": "min-width: 10rem"},
        col("reporters", "Reporter"),
        col("targets", "About"),
        col("items", "Items", numeric=True),
        {**col("missing", "Missing"), "style": "min-width: 12rem"},
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
                "missing": ", ".join(gaps(instrument)),
            }
        )
    return without_empty(columns, rows, "missing")


PARTS = {
    "items": "Items",
    "scores": "Scores",
    "analysis": "Item analysis",
    "dataset": "One dataset",
    "history": "History",
}


def detail(
    result: CatalogResult,
    instrument: Instrument,
    preferred: list[str],
    cfa: CfaView,
    view: BrowseView,
) -> None:
    about(result, instrument, wizard_done(view, cfa))
    datasets = administered_in(result, instrument.id)
    changes = file_history(result.project.root, result.project.instrument_files[instrument.id])
    shown = {
        "items": True,
        "scores": bool(datasets)
        and any(s.instrument_id == instrument.id for s in result.catalog.scores),
        "analysis": bool(datasets),
        "dataset": bool(datasets),
        "history": changes is not None,
    }
    if not shown.get(view.part):
        view.part = "items"

    def pick(name: str) -> None:
        view.part = name

    with (
        ui.tabs(value=view.part, on_change=lambda e: pick(e.value))
        .props("dense no-caps align=left")
        .classes("lc-subnav w-full") as tabs
    ):
        for name, on in shown.items():
            if on:
                ui.tab(name, label=PARTS[name])
    with ui.tab_panels(tabs, value=view.part).classes("w-full bg-transparent"):
        with ui.tab_panel("items").classes("lc-part"):
            definition(result, instrument)
        if shown["scores"]:
            with ui.tab_panel("scores").classes("lc-part"):
                scores_part(result, instrument, cfa)
        if shown["analysis"]:
            with ui.tab_panel("analysis").classes("lc-part"):
                items_part(result, instrument)
        if shown["dataset"]:
            with ui.tab_panel("dataset").classes("lc-part"):
                dataset_part(result, instrument, datasets, preferred, cfa)
        if shown["history"]:
            with ui.tab_panel("history").classes("lc-part"):
                history(result.project, instrument.id, changes)


def definition(result: CatalogResult, instrument: Instrument) -> None:
    reverse = sum(item.reverse for item in instrument.items)
    counted = f"{len(instrument.items)} items" + (f", {reverse} reverse-keyed" if reverse else "")
    with ui.row().classes("w-full gap-4 items-start"):
        with ui.column().classes("min-w-0").style("flex: 1 1 480px"), panel("Items", counted):
            table(*item_table(result, instrument))
        with ui.column().classes("gap-4").style("flex: 0 1 18rem"):
            for response_set in instrument.response_sets:
                with panel("Options", response_set.id):
                    table(
                        [col("value", "Value", numeric=True), col("label", "Label")],
                        [o.model_dump() for o in response_set.options],
                    )
            with panel("Missing codes"):
                table(*missing_code_table(result, instrument))


def scores_part(result: CatalogResult, instrument: Instrument, cfa: CfaView) -> None:
    with panel(
        "Score statistics",
        "α uses pairwise complete cases, as JASP's reliability analysis does; ω comes from the "
        "factor model on people who answered every item.",
    ):
        score_statistics(result, instrument, cfa)
    charts.score_charts(result, instrument.id)
    stable = stability_table(result, instrument)
    if stable is not None:
        with panel(
            "Stability across waves",
            f"{result.project.config.stats.coefficient()} between the same people's scores one "
            "wave apart (n people).",
        ):
            table(*stable)
    invariance_section(result, instrument, cfa, stable is not None)
    charts.other_scores(result, instrument.id)


def items_part(result: CatalogResult, instrument: Instrument) -> None:
    if instrument.kind == "demographics":
        with panel("Sample by wave"):
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
        with panel(f"Items in {dataset}"):
            table(*variable_table(result, instrument, dataset))
        factor_structure(result, instrument, dataset, cfa)
        measures_section(result, instrument, dataset, cfa)
        description_draft(result, instrument)
        charts.instrument_dataset_section(result, instrument.id, dataset)
        scoring_code(result, instrument, dataset)

    with ui.row().classes("items-center gap-3"):
        ui.label("Dataset").classes("lc-facet")
        ui.toggle(datasets, value=first, on_change=lambda e: one_dataset.refresh(e.value)).props(
            "dense no-caps"
        )
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
        table(*item_total_waves(result, instrument, score_id))

    with panel(
        "Item-total correlations",
        "r of each item with the sum of the other items answered; α without the item in "
        "brackets. Both use pairwise complete cases, as JASP's reliability analysis does.",
    ) as tools:
        if len(choices) > 1:
            with tools:
                ui.select(
                    choices, value=first, label="Score", on_change=lambda e: body.refresh(e.value)
                ).classes("w-64")
        body(first)


def history(project: Project, instrument_id: str, changes: list[Change]) -> None:
    path = project.instrument_files[instrument_id]
    with panel("History", f"Changes to {path} recorded in git; open one to see what changed."):
        if not changes:
            note(f"No commits include {path} yet.")
        for change in changes:
            caption = f"{change.date}, {change.author}" if change.commit else None
            with ui.expansion(change.message, caption=caption).classes("w-full"):
                ui.code(change.diff, language="diff").classes("w-full")


def about(
    result: CatalogResult, instrument: Instrument, done: Callable[[str], Awaitable[None]]
) -> None:
    variables = [v for v in result.catalog.variables if v.instrument_id == instrument.id]
    facts = [
        instrument.construct_name,
        reported(variables),
        *[
            f"{f.label or f.name.capitalize()}: {as_text(instrument.custom[f.name])}"
            for f in result.project.config.custom_fields
            if f.applies_to == "instrument" and f.name in instrument.custom
        ],
    ]
    with ui.column().classes("lc-panel lc-summary w-full gap-3"):
        with ui.column().classes("gap-1"):
            with ui.row().classes("items-center gap-3"):
                ui.label(instrument.name).classes("lc-summary-title")
                if instrument.abbreviation:
                    ui.label(instrument.abbreviation).classes("lc-pill lc-info")
            note(" · ".join(fact for fact in facts if fact))
        with ui.grid(columns="max-content 1fr").classes("lc-facts w-full"):
            if instrument.instructions:
                ui.label("Instructions").classes("lc-fact-key")
                ui.label(text_of(instrument.instructions)).classes("italic")
            if instrument.references:
                ui.label("Reference").classes("lc-fact-key")
                with ui.column().classes("gap-1 min-w-0"):
                    for reference in instrument.references:
                        reference_row(result.project, reference)
            if instrument.license:
                ui.label("License").classes("lc-fact-key")
                ui.label(instrument.license)
            if missing := gaps(instrument):
                ui.label("Missing").classes("lc-fact-key")
                with ui.row().classes("gap-1 items-center"):
                    for gap in missing:
                        ui.label(gap).classes("lc-pill lc-warn")
                    ui.button(
                        "Complete this instrument",
                        icon="edit_note",
                        on_click=lambda: new_instrument.open_wizard(result, done, instrument.id),
                    ).props("flat dense no-caps").classes("lc-quiet-btn")


def reference_row(project: Project, reference: Reference) -> None:
    pdf = reference_pdf(project, reference.pdf) if reference.pdf else None

    @ui.refreshable
    def links() -> None:
        with ui.row().classes("items-baseline gap-2"):
            cited(project.bibliography, reference.key)
            if pdf and is_placeholder(pdf):
                note("PDF not downloaded")
                get_button("Get", run_get, [[pdf]], got)
            elif pdf and pdf.is_file():
                ui.button("View PDF", on_click=lambda: toggle_viewer()).props("flat dense no-caps")
                ui.button("Open", on_click=lambda: open_path(pdf)).props("flat dense no-caps")
            elif pdf:
                note("PDF not found")

    async def got() -> None:
        links.refresh()

    links()
    viewer = ui.column().classes("w-full")

    # The PDF loads only when someone asks to see it.
    def toggle_viewer() -> None:
        if viewer.default_slot.children:
            viewer.clear()
            return
        with viewer:
            ui.element("iframe").props(f'src="{pdf_url(pdf)}"').classes("w-full").style(
                "height: 80vh; border: 1px solid var(--lc-border)"
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
    measures_section.refresh()
    invariance_section.refresh()


# Module level, so a finished CFA can redraw this table without redrawing the page.
@ui.refreshable
def score_statistics(result: CatalogResult, instrument: Instrument, cfa: CfaView) -> None:
    table(*score_table(result, instrument, cfa.fits))


def scoring_code(result: CatalogResult, instrument: Instrument, dataset: str) -> None:
    snippets = result.snippets.get((instrument.id, dataset))
    if snippets is not None:
        with panel(
            "Scoring code", f"R and Python that compute this instrument's scores in {dataset}"
        ):
            code_tabs(snippets)
    written_scripts(result, instrument, dataset)


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
            meta = await computed(
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

    with panel("Scoring script from the reference PDF", dataset):
        if preferences.model_set():
            with ui.row().classes("items-center gap-3"):
                button = ui.button("Write with the language model", on_click=write)
                status = ui.label().classes("lc-note")
        else:
            note("Set a language model on the Settings page to write the scripts from the PDF.")
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
    with panel("Factor structure", dataset):
        if cfa.status in (CFA_UNSET, CFA_RUNNING):
            note("Fitting factor models.")
        elif cfa.status == CFA_FAILED:
            note(cfa.message)
        elif not fits:
            note("No factor model: no score here has three or more items.")
        else:
            engine, estimator = fits[0].engine, fits[0].estimator
            ordinal = estimator == WLSMV
            package = "lavaan" if engine == R else "semopy"
            how = (
                "WLSMV with the items as ordered categories"
                if ordinal
                else "maximum likelihood with the items as continuous"
            )
            method = f"{package}, {how}, people who answered every item."
            omega = (
                "ω is semTools' categorical omega."
                if ordinal
                else "ω is the factor's share of the observed variance of the summed items, as "
                "semTools gives it for continuous items."
            )
            papers = {
                "cfa_fit": PaperTable(
                    f"Fit of Factor Models for {instrument.name}",
                    *without_empty(*without_empty(*fit_table(instrument, fits), "problem"), "srmr"),
                    method,
                ),
                "cfa_loadings": PaperTable(
                    f"Standardized Loadings and ω for {instrument.name}",
                    *loading_table(result, instrument, dataset, fits),
                    f"{method} {omega}",
                ),
            }
            for shown in papers.values():
                paper_table(shown)
            save_button(result, f"cfa_{instrument.id}_{dataset}", papers)
            if cfa.message:
                note(cfa.message)
            elif result.project.config.stats.cfa_estimator != estimator:
                # The project asks for ordered items, which only lavaan in R can fit.
                settings_hint(
                    cfa,
                    "This project's stats: cfa_estimator is wlsmv; set Rscript on the Settings "
                    "page to fit the items as ordered categories in lavaan.",
                )


def settings_hint(cfa: CfaView, text: str) -> None:
    with ui.row().classes("items-center gap-2"):
        note(text)
        if cfa.open_settings:
            ui.button("Open Settings", icon="settings", on_click=cfa.open_settings).props(
                "flat dense no-caps"
            )


@ui.refreshable
def measures_section(
    result: CatalogResult, instrument: Instrument, dataset: str, cfa: CfaView
) -> None:
    fits = [f for f in cfa.fits if (f.instrument_id, f.dataset) == (instrument.id, dataset)]
    text = measures.paragraph(
        result.project, result.catalog, result.summary, instrument, dataset, fits
    )
    with panel(
        "Measures paragraph",
        f"A draft for the paper's Measures section, with α and ω from {dataset}",
    ) as tools:
        with tools:
            copy_text(text)
        ui.label(text).classes("lc-prose")
        note(
            "Add description: to the instrument's YAML for what it measures; change the wording "
            "with measures: in labcatalog.yaml or in the instrument's YAML."
        )


def description_draft(result: CatalogResult, instrument: Instrument) -> None:
    if not ai_scoring.reference_pdfs(result.project, instrument):
        return
    path = result.project.instrument_files[instrument.id]

    async def write() -> None:
        button.disable()
        status.set_text("Reading the reference and drafting the description.")
        chosen = preferences.load()
        try:
            draft = await computed(
                run_description_draft,
                result,
                instrument.id,
                chosen.get(preferences.LLM_PROVIDER, preferences.DEFAULT_LLM_PROVIDER),
                chosen.get(preferences.LLM_MODEL, ""),
                chosen.get(preferences.LLM_URL, ""),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
        else:
            meta = draft.meta
            status.set_text(
                f"Drafted by {meta.model} in {meta.latency_ms / 1000:.0f} s, "
                f"{meta.input_tokens} tokens in and {meta.output_tokens} out."
            )
            shown.clear()
            with shown:
                ui.label(draft.description)
                copy_text(draft.description)
                note(f"Check it against the reference, then paste it as description: in {path}.")
                for line in draft.notes:
                    note(f"Note from the model: {line}")
        finally:
            button.enable()

    with panel("Description from the reference PDF", "For description: in the instrument's YAML"):
        if not preferences.model_set():
            note("Set a language model on the Settings page to draft the description from the PDF.")
            return
        with ui.row().classes("items-center gap-3"):
            button = ui.button("Draft the description", on_click=write)
            status = ui.label().classes("lc-note")
        shown = ui.column().classes("gap-1")


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
                "p": p_value(values.get("p")),
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
def invariance_section(
    result: CatalogResult, instrument: Instrument, cfa: CfaView, several_waves: bool
) -> None:
    tests = [t for t in cfa.invariance if t.instrument_id == instrument.id]
    if several_waves:
        with panel("Invariance across waves"):
            waves = [t for t in tests if t.across == WAVES]
            if cfa.invariance_status == CFA_UNSET:
                settings_hint(
                    cfa,
                    "Set the path to Rscript on the Settings page to test invariance across waves.",
                )
            elif cfa.invariance_status == CFA_RUNNING:
                note("Testing invariance across waves in R.")
            elif cfa.invariance_status == CFA_FAILED:
                note(cfa.invariance_message)
            elif not waves:
                note("No model: no score here has three or more items in two or more waves.")
            else:
                note("A drop in CFI of more than 0.01 is a common sign that a step does not hold.")
                method = invariance_view.method_text(result, WAVES, "waves")
                for i, test in enumerate(waves, start=1):
                    counts = ", ".join(
                        f"{views.wave_name(result, test.study, wave)} {n}"
                        for wave, n in test.n.items()
                    )
                    study = result.project.config.studies[test.study].label or test.study
                    invariance_view.test_block(
                        result,
                        instrument,
                        test,
                        f"Invariance of {instrument.name} Across Waves",
                        f"{method} n per wave: {counts}.",
                        f"{study}, reported by {test.reporter}; people who answered every item: "
                        f"{counts}.",
                        f"invariance_{instrument.id}_{i}",
                        lambda test=test: model_of(result, test),
                        cfa.reload,
                    )
    reporters = [t for t in tests if t.across == REPORTERS]
    if reporters:
        with panel("Invariance across reporters"):
            note("A drop in CFI of more than 0.01 is a common sign that a step does not hold.")
            method = invariance_view.method_text(result, REPORTERS, "reporters")
            for i, test in enumerate(reporters, start=1):
                counts = ", ".join(f"{reporter} {n}" for reporter, n in test.n.items())
                wave = views.wave_name(result, test.study, test.wave)
                invariance_view.test_block(
                    result,
                    instrument,
                    test,
                    f"Invariance of {instrument.name} Across Reporters, {wave}",
                    f"{method} n per reporter: {counts}.",
                    f"{wave}; answered every item: {counts}.",
                    f"invariance_reporters_{instrument.id}_{i}",
                    lambda test=test: model_of(result, test),
                    cfa.reload,
                )


def model_of(result: CatalogResult, test: InvarianceTest) -> InvarianceModel:
    return next(
        m
        for m in build_models(result.project, result.catalog, result.datasets)
        if (m.instrument_id, m.across, m.study, m.reporter, m.wave, m.kind)
        == (test.instrument_id, test.across, test.study, test.reporter, test.wave, test.kind)
        and list(m.factors) == list(test.factors)
    )


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
