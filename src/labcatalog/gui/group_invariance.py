from nicegui import run, ui

from labcatalog.charts import views
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import invariance as invariance_view
from labcatalog.gui import preferences
from labcatalog.gui.common import note, section
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats.group_invariance import MEASURE_SEPARATOR, group_models, measure_choices
from labcatalog.stats.invariance import fit_models


def render(result: CatalogResult, sample: analysis.Sample, view) -> None:
    labels = {name: views.dataset_label(result, name) for name in sample.datasets}
    groups = script.group_choices(result, sample.datasets, labels)
    measures = measure_choices(result, sample.datasets, view.instruments or [], labels)
    section("Measurement invariance across groups")
    if not groups or not measures:
        note(
            "Needs a demographics item with answer options and an instrument with three or more "
            "items per score in the chosen datasets."
        )
        return
    if view.invariance_group not in groups:
        view.invariance_group = next(iter(groups))
    if view.invariance_measure not in measures:
        view.invariance_measure = next(iter(measures))

    async def test() -> None:
        rscript = preferences.load().get(preferences.RSCRIPT)
        body.clear()
        if not rscript:
            with body:
                note("Set the path to Rscript on the Settings page to test invariance.")
            return
        with body:
            ui.spinner()
            note("Testing invariance across groups in R.")
        measure, group = view.invariance_measure, view.invariance_group
        estimator = result.project.config.stats.cfa_estimator
        try:
            models = await run.io_bound(group_models, result, sample, measure, group)
            tests = await run.io_bound(fit_models, models, rscript, estimator)
        except LabCatalogError as err:
            body.clear()
            with body:
                note(str(err))
            return
        if body.is_deleted:
            return
        body.clear()
        with body:
            show(models, tests, measure, group)

    def show(models, tests, measure: str, group: str) -> None:
        if not tests:
            note("Fewer than two groups have two or more people who answered every item.")
            return
        instrument = result.project.instruments[measure.split(MEASURE_SEPARATOR)[0]]
        method = invariance_view.method_text(result, "groups", groups[group])
        note("A drop in CFI of more than 0.01 is a common sign that a step does not hold.")
        for i, (model, found) in enumerate(zip(models, tests, strict=True), start=1):
            counts = ", ".join(f"{label} {n}" for label, n in found.n.items())
            if model.left_out:
                small = ", ".join(f"{label} ({n})" for label, n in model.left_out.items())
                counts += f"; left out, more items than people: {small}"
            invariance_view.test_block(
                result,
                instrument,
                found,
                f"Invariance of {instrument.name} Across {groups[group]}",
                f"{method} n per group: {counts}.",
                f"{measures[measure]}; answered every item: {counts}.",
                f"invariance_groups_{instrument.id}_{i}",
                lambda model=model: model,
                test,
            )

    def choose(key: str, value: str) -> None:
        setattr(view, key, value)
        body.clear()

    with ui.row().classes("w-full items-center gap-4"):
        ui.select(
            measures,
            value=view.invariance_measure,
            label="Instrument",
            with_input=True,
            on_change=lambda e: choose("invariance_measure", e.value),
        ).props("dense outlined").classes("w-96")
        ui.select(
            groups,
            value=view.invariance_group,
            label="Groups",
            with_input=True,
            on_change=lambda e: choose("invariance_group", e.value),
        ).props("dense outlined").classes("min-w-96 grow")
        ui.button("Test", icon="play_arrow", on_click=test).props("no-caps")
    body = ui.column().classes("w-full gap-2")
