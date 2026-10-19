from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial

from nicegui import ui

from labcatalog.config import PrepareStep, dataset_by_name
from labcatalog.data.prepare import step_state, step_states
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import prepare
from labcatalog.gui.common import computed, empty, folding_panel, note, page_head, panel
from labcatalog.gui.filter_bar import Filters, filter_bar
from labcatalog.gui.prepare import PrepareView
from labcatalog.gui.script_editor import script_editor
from labcatalog.metadata import changes, editing
from labcatalog.metadata.browse import row_counts, row_matches
from labcatalog.metadata.scripts import (
    ANALYSIS,
    KINDS,
    LANGUAGES,
    PREPARE,
    UNUSED,
    Entry,
    Script,
    command,
    entries,
    language_of,
    new_script,
    project_scripts,
    remove_step_change,
    script_index,
    step_change,
    written,
)
from labcatalog.pipeline import CatalogResult
from labcatalog.project import Project


@dataclass
class ScriptsView:
    # The line shown: a script's path, or step: and the name of a step that names no script.
    key: str | None = None
    edited: bool = False
    filters: Filters = field(default_factory=Filters)


def render(
    result: CatalogResult,
    view: ScriptsView,
    running: PrepareView,
    on_saved: Callable[[], Awaitable[None]],
) -> None:
    project = result.project
    found = project_scripts(project)
    listed = entries(project, found)
    by_key = {e.key: e for e in listed}
    statuses = {s.step.name: s.status for s in step_states(project)}
    index = script_index(project, listed, statuses)
    filters = view.filters

    def leave(then: Callable[[], None]) -> None:
        if not view.edited:
            then()
            return
        with frame, ui.dialog() as dialog, ui.card():
            ui.label(f"Discard your changes to {view.key}?")
            with ui.row():
                ui.button("Discard", on_click=lambda: (dialog.close(), then()))
                ui.button("Keep editing", on_click=dialog.close).props("flat")
        dialog.open()

    def go(key: str) -> None:
        view.key, view.edited = key, False
        page.refresh()

    async def made(language: str, name: str, dialog: ui.dialog) -> None:
        try:
            path = new_script(project.root, name.strip(), language)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative")
            return
        dialog.close()
        view.key, view.edited = path, False
        filters.selected.clear()
        filters.query = ""
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

    def line(entry: Entry, steps: list[PrepareStep]) -> None:
        title = entry.script.path.split("/")[-1] if entry.script else entry.step.name
        item = (
            ui.item(title, on_click=partial(leave, partial(go, entry.key)))
            .props("dense clickable")
            .classes("lc-pick")
        )
        if entry.key == view.key:
            item.classes("lc-info font-medium")
        if entry.script is None:
            item.tooltip("Its command names no script in the project")
        for step in steps if entry.script else []:
            ui.label(step.name).classes("lc-note pl-6 -mt-1")

    @ui.refreshable
    def page() -> None:
        kept = [by_key[k] for k in row_matches(index, filters.selected, filters.query)]
        if view.key not in {e.key for e in kept}:
            view.key = kept[0].key if kept else None
        with ui.row().classes("w-full no-wrap items-start gap-6"):
            with ui.column().classes("w-64 shrink-0 lc-side"):
                if not kept:
                    note("No script matches the search and filters.")
                for title, rows in groups(project, kept):
                    with panel(title), ui.column().classes("w-full gap-0"):
                        for entry, steps in rows:
                            line(entry, steps)
            with ui.column().classes("grow min-w-0 gap-4"):
                entry = by_key.get(view.key)
                if entry is None:
                    empty("No scripts yet; press New script to write one.", "code")
                elif entry.script:
                    script_part(result, entry.script, view, running, page.refresh, on_saved)
                else:
                    steps_part(result, None, [entry.step], running, page.refresh, on_saved)
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
        filter_bar(
            index.facets,
            lambda: row_counts(index, filters.selected, filters.query),
            filters,
            page.refresh,
        )
        page()


def groups(
    project: Project, kept: list[Entry]
) -> list[tuple[str, list[tuple[Entry, list[PrepareStep]]]]]:
    # Prepare scripts by the modality of what their steps write, each with those steps.
    config = project.config
    by_modality: dict[str, list[tuple[Entry, list[PrepareStep]]]] = {}
    for entry in (e for e in kept if e.kind == PREPARE):
        steps: dict[str, list[PrepareStep]] = {}
        for step in entry.steps:
            modalities = {dataset_by_name(config, d).modality for d in written(project, [step])}
            for modality in modalities or {""}:
                steps.setdefault(modality, []).append(step)
        for modality, own in steps.items():
            by_modality.setdefault(modality, []).append((entry, own))
    order = config.vocab.modalities

    def place(modality: str) -> tuple[bool, int]:
        return modality == "", order.index(modality) if modality in order else len(order)

    found = [
        (config.vocab.modality_label(m) if m else "Other steps", by_modality[m])
        for m in sorted(by_modality, key=place)
    ]
    for kind in (ANALYSIS, UNUSED):
        rows = [(e, []) for e in kept if e.kind == kind]
        if rows:
            found.append((KINDS[kind], rows))
    return found


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
