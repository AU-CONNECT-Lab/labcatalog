from collections.abc import Awaitable, Callable

from nicegui import run, ui

from labcatalog.config import FreedParameter
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences
from labcatalog.gui.common import col, computed, fmt, note, p_value, table
from labcatalog.gui.paper import paper_table, results_text, save_button, without_empty
from labcatalog.metadata.editing import save_freed
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.schema import Instrument
from labcatalog.stats import invariance
from labcatalog.stats.cfa import SUBSCALES, WLSMV
from labcatalog.stats.invariance import (
    REPORTERS,
    STEPS,
    WAVES,
    InvarianceModel,
    InvarianceTest,
    ScoreTest,
)

STEP_NAMES = {
    "configural": "Configural",
    "thresholds": "Thresholds",
    "metric": "Metric (+ loadings)",
    "scalar": "Scalar (+ intercepts)",
}
PARAMETERS = {"loading": "loading", "threshold": "thresholds", "intercept": "intercept"}

Reload = Callable[[], Awaitable[None]]


def method_text(result: CatalogResult, across: str, by: str) -> str:
    # by names what the occasions are: waves, reporters, or the groups of an item.
    config = result.project.config
    how = (
        "WLSMV with the items as ordered categories, people who answered every item. Each step "
        f"holds one more set of parameters equal across {by}; Δχ² is the scaled difference test"
        if config.stats.cfa_estimator == WLSMV
        else "maximum likelihood with the items as continuous, full information for people "
        f"missing {'a wave' if across == WAVES else 'an occasion'}. Each step holds one more set "
        f"of parameters equal across {by}; Δχ² is the likelihood ratio test"
    )
    if across == WAVES:
        model = (
            "each wave's items load on their own factors, the same people are linked by ID, and "
            "each item's residuals correlate across waves"
        )
    elif across == REPORTERS:
        model = (
            "each reporter's items load on their own factors, the reporters of one "
            f"{config.stats.correlate_by} are linked, and each item's residuals correlate across "
            "reporters"
        )
    else:
        model = f"a multigroup model with one group per answer to {by}"
    return f"lavaan and semTools: {model}; {how} against the step before."


def model_heading(instrument: Instrument, test: InvarianceTest) -> str:
    labels = {s.id: s.label for s in instrument.scores}
    kind = "Subscales" if test.kind == SUBSCALES else "One factor"
    return f"{kind}: {', '.join(labels[s] for s in test.factors)}"


def freed_text(instrument: Instrument, freed: list[FreedParameter]) -> str:
    return ", ".join(f"{item_name(instrument, f.item)} {PARAMETERS[f.parameter]}" for f in freed)


def item_name(instrument: Instrument, item_id: str) -> str:
    item = next((i for i in instrument.items if i.id == item_id), None)
    return f"{item_id} ({item.label})" if item is not None and item.label else item_id


def test_block(
    result: CatalogResult,
    instrument: Instrument,
    test: InvarianceTest,
    title: str,
    method: str,
    who: str,
    name: str,
    model: Callable[[], InvarianceModel],
    reload: Reload | None,
    across: str,
) -> None:
    heading = model_heading(instrument, test)
    ui.label(heading).classes("font-medium mt-2")
    note(who)
    if test.freed:
        note(f"Freed, as labcatalog.yaml says: {freed_text(instrument, test.freed)}.")
    if test.problem:
        note(test.problem)
        return
    shown = PaperTable(
        f"{title} ({heading})",
        *without_empty(*invariance_table(test), "problem"),
        method + (f" Freed: {freed_text(instrument, test.freed)}." if test.freed else ""),
    )
    paper_table(shown)
    labels = {s.id: s.label for s in instrument.scores}
    freed = freed_text(instrument, test.freed)
    results_text(results.invariance_text(test, labels, across, freed), [shown])
    with ui.row().classes("items-center gap-2"):
        steps = [s.step for s in test.steps if s.step != "configural" and not s.problem]
        if steps:
            ui.button(
                "Which items differ",
                icon="rule",
                on_click=lambda: score_dialog(result, instrument, test, steps, model, reload),
            ).props("flat dense no-caps")
        save_button(result, name, {"invariance": shown})


def invariance_table(test: InvarianceTest) -> tuple[list[dict], list[dict]]:
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
                "step": STEP_NAMES[step.step],
                "chisq": f"{fmt(values['chisq'])} ({values['df']:g})" if values else "",
                **{key: fmt(values.get(key), 3) for key in ("cfi", "rmsea", "srmr")},
                "diff": f"{fmt(step.chisq_diff)} ({step.df_diff:g})"
                if step.chisq_diff is not None
                else "",
                "p": p_value(step.p_diff),
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


def score_rows(instrument: Instrument, found: list[ScoreTest]) -> list[dict]:
    return [
        {
            "item": s.item,
            "name": item_name(instrument, s.item),
            "chisq": f"{fmt(s.chisq)} ({s.df:g})" if s.chisq is not None else "",
            "p": p_value(s.p),
        }
        for s in sorted(found, key=lambda s: -(s.chisq or 0))
    ]


def score_dialog(
    result: CatalogResult,
    instrument: Instrument,
    test: InvarianceTest,
    steps: list[str],
    model: Callable[[], InvarianceModel],
    reload: Reload | None,
) -> None:
    config = result.project.config
    estimator = config.stats.cfa_estimator
    chosen = {"step": steps[0]}
    ticked: set[tuple[str, str]] = set()

    async def compute() -> None:
        body.clear()
        with body:
            ui.spinner()
            note("Running the score tests in R; each item takes a few seconds.")
        rscript = preferences.load().get(preferences.RSCRIPT)
        try:
            built = await computed(model)
            found = await computed(
                invariance.score_tests, built, chosen["step"], rscript, estimator
            )
        except (LabCatalogError, ValueError) as err:
            body.clear()
            with body:
                note(str(err))
            return
        show(found)

    def show(found: list[ScoreTest]) -> None:
        body.clear()
        parameter = invariance.STEP_PARAMETER[chosen["step"]]
        with body:
            note(
                f"Each row tests freeing the item's {PARAMETERS[parameter]} on every occasion at "
                "once, in the model of this step (lavaan's score test, mean-scaled under WLSMV). "
                "Tick the items to free, then save; the tests rerun with them freed."
            )
            columns = [
                col("name", "Item"),
                col("chisq", "χ² (df)", numeric=True),
                col("p", "p", numeric=True),
            ]
            shown = table(columns, score_rows(instrument, found))
            shown.set_selection("multiple")
            shown.on_select(
                lambda: replace_ticked(parameter, [row["item"] for row in shown.selected])
            )

    def replace_ticked(parameter: str, items: list[str]) -> None:
        ticked.difference_update({t for t in ticked if t[1] == parameter})
        ticked.update((item, parameter) for item in items)

    async def save() -> None:
        here = (instrument.id, test.across)
        kept = [
            f
            for f in config.stats.invariance_free
            if (f.instrument, f.across) != here or (f.item, f.parameter) not in removed
        ]
        known = {(f.item, f.parameter) for f in kept if (f.instrument, f.across) == here}
        added = [
            FreedParameter(instrument=instrument.id, item=i, parameter=p, across=test.across)
            for i, p in sorted(ticked - known)
        ]
        await run.io_bound(save_freed, result.project.root, kept + added)
        # The file and the loaded settings now agree, so a rerun reads the new list.
        config.stats.invariance_free = kept + added
        dialog.close()
        if reload is not None:
            await reload()

    removed: set[tuple[str, str]] = set()
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
        ui.label(f"Which items differ: {model_heading(instrument, test)}").classes("text-lg")
        if test.freed:
            with ui.row().classes("items-center gap-4"):
                note("Freed now; untick to hold equal again:")
                for f in test.freed:
                    key = (f.item, f.parameter)
                    ui.checkbox(
                        f"{item_name(instrument, f.item)} {PARAMETERS[f.parameter]}",
                        value=True,
                        on_change=lambda e, key=key: (removed.discard if e.value else removed.add)(
                            key
                        ),
                    )
        with ui.row().classes("items-center gap-2"):
            ui.select(
                {s: STEP_NAMES[s] for s in steps},
                value=chosen["step"],
                label="Step",
                on_change=lambda e: chosen.update(step=e.value),
            ).classes("w-56")
            ui.button("Run", icon="play_arrow", on_click=compute).props("no-caps")
        body = ui.column().classes("w-full")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Save and rerun", icon="save", on_click=save).props("no-caps")
    dialog.open()
