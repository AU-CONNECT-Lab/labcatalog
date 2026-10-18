from collections.abc import Awaitable, Callable

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, note, open_path, panel
from labcatalog.gui.files import choose_path
from labcatalog.metadata import scoring_steps
from labcatalog.paths import posix_str
from labcatalog.pipeline import CatalogResult
from labcatalog.schema import SCRIPT, Instrument

FILE_TYPES = ("R or Python scripts (*.R;*.py)",)


def render(
    result: CatalogResult,
    instrument: Instrument,
    dataset: str,
    reload: Callable[[], Awaitable[None]],
) -> None:
    project = result.project
    step = scoring_steps.registered(project, instrument.id, dataset)
    scripted = [s.label for s in instrument.scores if s.method == SCRIPT]
    if step is None and not scripted:
        return

    async def start(language: str) -> None:
        script = await computed(
            scoring_steps.start_script, project, result.catalog, instrument.id, dataset, language
        )
        await use(script)

    async def own() -> None:
        chosen = await choose_path(file_types=FILE_TYPES, start=project.root)
        if chosen is None:
            return
        if not chosen.resolve().is_relative_to(project.root.resolve()):
            ui.notify("Choose a script inside the project folder", type="warning")
            return
        await use(posix_str(chosen.resolve().relative_to(project.root.resolve())))

    async def use(script: str) -> None:
        await registered(result, instrument, dataset, script, reload)

    with panel("Scoring step", f"The script that computes scores in {dataset}"):
        if step is not None:
            note(
                f"Prepare data on the Set up page runs {step.run}, which writes "
                f"{step.outputs[0]}; the scores are read from there."
            )
            script = step.inputs[-1]
            ui.button(
                f"Open {script}",
                icon="open_in_new",
                on_click=lambda: open_path(project.root / script),
            ).props("flat dense no-caps")
            return
        note(
            f"{', '.join(scripted)} {'is' if len(scripted) == 1 else 'are'} computed by a script. "
            "Start one from a template that reads the data and writes each score's column, or use "
            "a script of your own that does the same; either becomes a step of Prepare data."
        )
        with ui.row().classes("items-center gap-2"):
            ui.button("Start an R script", icon="note_add", on_click=lambda: start("r")).props(
                "flat no-caps"
            )
            ui.button(
                "Start a Python script", icon="note_add", on_click=lambda: start("python")
            ).props("flat no-caps")
            ui.button("Use my own script", icon="folder_open", on_click=own).props("flat no-caps")


async def registered(
    result: CatalogResult,
    instrument: Instrument,
    dataset: str,
    script: str,
    reload: Callable[[], Awaitable[None]],
) -> None:
    try:
        step = await computed(
            scoring_steps.register, result.project, instrument.id, dataset, script
        )
    except LabCatalogError as err:
        ui.notify(str(err), type="negative", multi_line=True)
        return
    ui.notify(f"Added the step {step.name}; run it in Prepare data on the Set up page")
    await reload()


def use_button(
    result: CatalogResult,
    instrument: Instrument,
    dataset: str,
    script: str,
    reload: Callable[[], Awaitable[None]],
) -> None:
    # A script written from the reference becomes the scoring step, its scores checked or used.
    ui.button(
        f"Use {script} as the scoring step",
        icon="playlist_add",
        on_click=lambda: registered(result, instrument, dataset, script, reload),
    ).props("flat dense no-caps")
