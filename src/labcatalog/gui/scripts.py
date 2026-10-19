from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from nicegui import ui

from labcatalog.config import PrepareStep
from labcatalog.data.prepare import step_state
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import prepare
from labcatalog.gui.common import computed, empty, folding_panel, note, page_head, panel
from labcatalog.gui.prepare import PrepareView
from labcatalog.gui.script_editor import script_editor
from labcatalog.metadata import changes, editing
from labcatalog.metadata.scripts import (
    LANGUAGES,
    Script,
    command,
    language_of,
    new_script,
    project_scripts,
    remove_step_change,
    step_change,
)
from labcatalog.pipeline import CatalogResult


@dataclass
class ScriptsView:
    # The script shown, or a step whose command names no script.
    path: str | None = None
    step: str | None = None
    edited: bool = False


def render(
    result: CatalogResult,
    view: ScriptsView,
    running: PrepareView,
    on_saved: Callable[[], Awaitable[None]],
) -> None:
    project = result.project
    found = project_scripts(project)
    listed = [*found.steps, *found.analyses, *(Script(p) for p in found.unused)]
    by_path = {s.path: s for s in listed}
    loose = {s.name: s for s in found.commands}
    if view.path not in by_path and view.step not in loose:
        view.path = listed[0].path if listed else None
        view.step = None if listed or not loose else next(iter(loose))

    def leave(then: Callable[[], None]) -> None:
        if not view.edited:
            then()
            return
        with frame, ui.dialog() as dialog, ui.card():
            ui.label(f"Discard your changes to {view.path}?")
            with ui.row():
                ui.button("Discard", on_click=lambda: (dialog.close(), then()))
                ui.button("Keep editing", on_click=dialog.close).props("flat")
        dialog.open()

    def go(path: str | None, step: str | None = None) -> None:
        view.path, view.step, view.edited = path, step, False
        page.refresh()

    def pick(item, chosen: bool) -> None:
        item.props("dense clickable").classes("lc-pick")
        if chosen:
            item.classes("lc-info font-medium")

    async def made(language: str, name: str, dialog: ui.dialog) -> None:
        try:
            path = new_script(project.root, name.strip(), language)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative")
            return
        dialog.close()
        view.path, view.step, view.edited = path, None, False
        await on_saved()

    def new_dialog() -> None:
        with frame, ui.dialog() as dialog, ui.card().classes("w-[32rem] max-w-full"):
            ui.label("New script").classes("text-lg font-medium")
            name = ui.input("Name", placeholder="clean_parent").classes("w-full")
            language = ui.toggle({k: v.name for k, v in LANGUAGES.items()}, value="r").props(
                "dense no-caps"
            )
            note("Written to scripts/ with lines that read its input and write its output.")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Create", on_click=lambda: made(language.value, name.value or "", dialog))
        dialog.open()

    @ui.refreshable
    def page() -> None:
        with ui.row().classes("w-full no-wrap items-start gap-6"):
            with ui.column().classes("w-64 shrink-0 lc-side"):
                groups = (
                    ("Prepare steps", found.steps, "The scripts the prepare steps run"),
                    ("Analyses", found.analyses, "Kept from the Custom tab of the Analysis page"),
                    ("Not run", [Script(p) for p in found.unused], "Nothing runs these yet"),
                )
                for title, scripts, help_text in groups:
                    if not scripts and not (title == "Prepare steps" and loose):
                        continue
                    with panel(title, help_text=help_text), ui.column().classes("w-full gap-0"):
                        for script in scripts:
                            item = ui.item(
                                script.path.split("/")[-1],
                                on_click=partial(leave, partial(go, script.path)),
                            )
                            pick(item, script.path == view.path)
                            if len(script.steps) > 1:
                                item.tooltip(f"Run by {len(script.steps)} steps")
                        if title == "Prepare steps":
                            for name in loose:
                                item = ui.item(
                                    name, on_click=partial(leave, partial(go, None, name))
                                )
                                pick(item, name == view.step)
                                item.tooltip("Its command names no script in the project")
            with ui.column().classes("grow min-w-0 gap-4"):
                if view.path in by_path:
                    script_part(result, by_path[view.path], view, running, page.refresh, on_saved)
                elif view.step in loose:
                    steps_part(result, None, [loose[view.step]], running, page.refresh, on_saved)
                else:
                    empty("No scripts yet; press New script to write one.", "code")
        with folding_panel(
            "Draft a cleaning step",
            help_text="A language model writes a script that turns a raw export into a dataset's file",
        ):
            prepare.draft_panel(result, on_saved)

    with ui.column().classes("w-full gap-4") as frame:
        counted = f"{len(found.steps)} run by prepare steps, {len(found.analyses)} analyses"
        with page_head(
            "Scripts",
            counted,
            help_text="Every script of the project: what runs it, its code and its last run.",
        ):
            ui.button("New script", icon="add", on_click=lambda: leave(new_dialog)).props(
                "flat no-caps"
            )
        page()


def script_part(
    result: CatalogResult,
    script: Script,
    view: ScriptsView,
    running: PrepareView,
    redraw: Callable[[], None],
    on_saved: Callable[[], Awaitable[None]],
) -> None:
    root = result.project.root

    def edited() -> None:
        view.edited = True

    def saved() -> None:
        view.edited = False
        redraw()

    with panel(
        script.path, help_text="The script's code; saving it puts its steps out of date"
    ) as tools:
        script_editor(root, script.path, tools, on_edit=edited, on_saved=saved)
    if script.analysis:
        analysis_part(result, script, on_saved)
    else:
        steps_part(result, script, script.steps, running, redraw, on_saved)


def steps_part(
    result: CatalogResult,
    script: Script | None,
    steps: list[PrepareStep],
    running: PrepareView,
    redraw: Callable[[], None],
    on_saved: Callable[[], Awaitable[None]],
) -> None:
    project = result.project

    async def start(names: list[str]) -> None:
        await prepare.run_chosen(project, running, names, redraw, on_saved)

    def show_log(name: str) -> None:
        running.shown = name
        redraw()

    async def write(change, done: str) -> bool:
        try:
            issues = await computed(changes.check, project, [change])
            if issues:
                ui.notify(
                    "Not saved: " + "; ".join(i.message for i in issues),
                    type="warning",
                    multi_line=True,
                )
                return False
            changes.write(project, [change])
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return False
        ui.notify(done)
        await on_saved()
        return True

    def edit_dialog(step: PrepareStep | None) -> None:
        stem = script.path.split("/")[-1].rsplit(".", 1)[0] if script else "step"
        language = language_of(script.path) if script else None
        start_from = step or PrepareStep(
            name=stem,
            run=command(language, script.path, "INPUT", "OUTPUT") if language else "",
            inputs=[script.path] if script else [],
            outputs=[],
        )
        with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full"):
            ui.label("Edit the step" if step else "Add a step").classes("text-lg font-medium")
            name = ui.input("Name", value=start_from.name).classes("w-full")
            run = ui.input("Command", value=start_from.run).classes("w-full font-mono")
            note(
                "Runs in the project folder. A file the command reads is an input; one it writes is an output."
            )
            inputs = (
                ui.textarea("Inputs, one per line", value="\n".join(start_from.inputs))
                .props("outlined")
                .classes("lc-grow w-full")
            )
            outputs = (
                ui.textarea("Outputs, one per line", value="\n".join(start_from.outputs))
                .props("outlined")
                .classes("lc-grow w-full")
            )

            async def save() -> None:
                def lines(box: ui.textarea) -> list[str]:
                    return [line.strip() for line in (box.value or "").splitlines() if line.strip()]

                try:
                    found = PrepareStep(
                        name=(name.value or "").strip(),
                        run=(run.value or "").strip(),
                        inputs=lines(inputs),
                        outputs=lines(outputs),
                    )
                    change = step_change(project, step.name if step else None, found)
                except (LabCatalogError, ValueError) as err:
                    ui.notify(str(err), type="negative", multi_line=True)
                    return
                if await write(change, f"Saved the step {found.name}"):
                    dialog.close()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=save)
        dialog.open()

    def remove_dialog(step: PrepareStep) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Remove the step {step.name}? The script and the files stay.")

            async def go() -> None:
                dialog.close()
                await write(remove_step_change(project, step.name), f"Removed {step.name}")

            with ui.row():
                ui.button("Remove", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    title = "Steps that run it" if script else "Step"
    with panel(title, help_text="Each step runs a command in the project folder") as tools:
        if not steps:
            note("No step runs this script yet.")
        for step in steps:
            state = step_state(project, step)
            prepare.step_row(state, running, start, show_log, on_saved)
            with ui.row().classes("gap-1 -mt-2 mb-2 ml-6"):
                ui.button("Edit", icon="edit", on_click=partial(edit_dialog, step)).props(
                    "flat dense no-caps"
                ).classes("lc-quiet-btn")
                ui.button("Remove", icon="delete", on_click=partial(remove_dialog, step)).props(
                    "flat dense no-caps"
                ).classes("lc-quiet-btn")
    if script:
        with tools:
            ui.button("Add a step", icon="add", on_click=lambda: edit_dialog(None)).props(
                "flat dense no-caps"
            ).classes("lc-quiet-btn")
    prepare.log_panel(running)


def analysis_part(
    result: CatalogResult, script: Script, on_saved: Callable[[], Awaitable[None]]
) -> None:
    analysis = script.analysis
    root = result.project.root

    def remove_dialog() -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete {script.path} and its entry under analyses in labcatalog.yaml?")

            async def go() -> None:
                dialog.close()
                editing.remove_analysis(root, analysis)
                ui.notify(f"Deleted {analysis.name}")
                await on_saved()

            with ui.row():
                ui.button("Delete", on_click=go).props("color=negative")
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    with panel(analysis.name, help_text="Run it on the Custom tab of the Analysis page") as tools:
        if analysis.request:
            ui.label(analysis.request).classes("lc-prose")
        ui.label(f"Datasets: {', '.join(analysis.datasets)}").classes("lc-note")
        if analysis.variables:
            ui.label(f"Variables: {', '.join(analysis.variables)}").classes("lc-note")
    with tools:
        ui.button("Delete", icon="delete", on_click=remove_dialog).props(
            "flat dense no-caps"
        ).classes("lc-quiet-btn")
