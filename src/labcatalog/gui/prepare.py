from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from nicegui import ui

from labcatalog import defaults
from labcatalog.ai.cleaning import cleaning_step, raw_of
from labcatalog.data.prepare import FileState, Session, StepState, run_steps, step_states, stop
from labcatalog.exceptions import DataladError, LabCatalogError, PrepareBusyError
from labcatalog.gui import common, preferences
from labcatalog.gui.cleaning import LANGUAGE_NAMES, review, sent_text
from labcatalog.gui.common import computed, empty, note, open_path, page_head, panel, path_input
from labcatalog.gui.datalad import get_button
from labcatalog.gui.files import choose_path
from labcatalog.paths import portable_path, posix_str
from labcatalog.pipeline import CatalogResult, run_cleaning_draft, run_get
from labcatalog.project import load_project

EXAMPLE = """\
prepare:
  - name: clean_parent_w1
    run: Rscript scripts/clean_parent.R
    inputs: [raw/parent_w1_export.csv, scripts/clean_parent.R]
    outputs: [data/parent_w1.csv]
"""
STATUS_KINDS = {
    "up to date": "ok",
    "outdated": "warn",
    "missing output": "bad",
    "missing input": "bad",
}
POLL_SECONDS = 0.3
NO_LOG = "Run a step to see its output here"


@dataclass
class PrepareView:
    session: Session = field(default_factory=Session)
    running: bool = False
    shown: str | None = None


def render(
    root: Path,
    result: CatalogResult | None,
    view: PrepareView,
    on_success: Callable[[], Awaitable[None]],
) -> None:
    try:
        project = load_project(root)
    except LabCatalogError as err:
        empty(str(err), "error")
        return
    config_path = root / defaults.CONFIG_FILENAME
    if not project.config.prepare:
        with panel(
            "No prepare steps yet",
            f"Add them to {defaults.CONFIG_FILENAME} like this; each step runs one command in "
            "the project folder, and its outputs are usually the data files listed under "
            "datasets.",
        ) as tools:
            ui.code(EXAMPLE, language="yaml").classes("w-full")
        with tools:
            ui.button(
                f"Open {defaults.CONFIG_FILENAME}", on_click=lambda: open_path(config_path)
            ).props("flat no-caps").classes("lc-quiet-btn")
        draft_panel(result, on_success)
        return
    names = [step.name for step in project.config.prepare]

    async def start(chosen: list[str], outdated_only: bool = False, anyway: bool = False) -> None:
        view.running = True
        steps.refresh()
        tools = preferences.load()
        try:
            runs = await computed(
                run_steps,
                project,
                chosen,
                view.session,
                outdated_only,
                None,
                tools.get(preferences.RSCRIPT),
                tools.get(preferences.DATALAD),
                anyway,
                preferences.step_python(),
            )
        except PrepareBusyError as err:
            view.running = False
            steps.refresh()
            confirm_busy(err, lambda: start(chosen, outdated_only, anyway=True))
            return
        except DataladError as err:
            view.running = False
            steps.refresh()
            ui.notify(str(err), type="negative", multi_line=True)
            return
        view.running = False
        if runs:
            view.shown = runs[-1].name
        steps.refresh()
        if not runs:
            ui.notify("Every step is up to date")
        elif any(r.exit_code == 0 for r in runs):
            await on_success()

    def confirm_all() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
            ui.label("Run every step in this order? A step that fails stops the rest.")
            for step in project.config.prepare:
                with ui.row().classes("items-baseline gap-2 no-wrap"):
                    ui.label(step.name).classes("font-medium")
                    ui.label(step.run).classes("font-mono lc-note")

            async def go() -> None:
                dialog.close()
                await start(names)

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Run all", on_click=go)
        dialog.open()

    def show_log(name: str) -> None:
        view.shown = name
        steps.refresh()

    help_text = (
        "Runs your own cleaning scripts, one command per step, in the project folder. A step "
        "is outdated when one of its inputs is newer than its outputs. A step can call "
        "Rscript by name once its path is set on the Settings page."
        + (
            " Each step runs through datalad run, which gets missing inputs first and records "
            "the run in the dataset's history."
            if project.config.prepare_with == "datalad"
            else ""
        )
    )

    @ui.refreshable
    def steps() -> None:
        states = step_states(project)
        waiting = sum(s.status != "up to date" for s in states)
        counted = f"{len(states)} steps, " + (f"{waiting} to run" if waiting else "all up to date")
        with page_head("Prepare", counted, help_text):
            ui.button(
                f"Open {defaults.CONFIG_FILENAME}", on_click=lambda: open_path(config_path)
            ).props("flat no-caps")
            ui.button("Stop", icon="stop", on_click=lambda: stop(view.session)).props(
                "flat no-caps"
            ).classes("lc-quiet-btn").set_enabled(view.running)
            ui.button(
                "Run outdated", icon="update", on_click=lambda: start(names, outdated_only=True)
            ).props("flat no-caps").classes("lc-quiet-btn").set_enabled(not view.running)
            ui.button("Run all", icon="play_arrow", on_click=confirm_all).set_enabled(
                not view.running
            )
        with panel("Steps", "In the order they run"):
            for state in states:
                step_row(state, view, start, show_log, on_success)
        log_panel(view)
        draft_panel(result, on_success)

    steps()


def confirm_busy(err: PrepareBusyError, run_anyway: Callable[[], Awaitable[None]]) -> None:
    with ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full"):
        ui.label(
            f"{err.by} has been running the prepare steps since {err.since:%H:%M on %Y-%m-%d}. "
            "Running them at the same time writes the same files twice. Run them anyway only "
            "if that run has ended, for example because its window was closed."
        )

        async def go() -> None:
            dialog.close()
            await run_anyway()

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Run anyway", on_click=go)
    dialog.open()


def step_row(
    state: StepState,
    view: PrepareView,
    start: Callable[[list[str]], Awaitable[None]],
    show_log: Callable[[str], None],
    on_got: Callable[[], Awaitable[None]],
) -> None:
    step = state.step
    last = view.session.runs.get(step.name)
    kind = STATUS_KINDS[state.status]
    with ui.row().classes("lc-item w-full items-start no-wrap gap-3"):
        ui.element("span").classes(f"lc-dot lc-{kind} mt-2")
        with ui.column().classes("grow min-w-0 gap-0"):
            with ui.row().classes("items-center gap-3"):
                ui.label(step.name).classes("lc-item-title")
                ui.label(state.status).classes(f"lc-pill lc-{kind}")
                if last:
                    ui.label(f"Last run: {last.outcome}").classes("lc-note")
            ui.label(step.run).classes("lc-step-run")
            with ui.grid(columns="auto 1fr").classes("lc-step-files gap-x-4 gap-y-0"):
                for label, files in (("Inputs", state.inputs), ("Outputs", state.outputs)):
                    if files:
                        ui.label(label).classes("lc-faint")
                        with ui.row().classes("gap-x-4 gap-y-0"):
                            for f in files:
                                file_label(f, on_got)
        with ui.row().classes("items-center no-wrap gap-1"):
            if last:
                ui.button("Log", on_click=lambda: show_log(step.name)).props("flat dense no-caps")
            ui.button("Run", icon="play_arrow", on_click=lambda: start([step.name])).props(
                "flat dense no-caps"
            ).classes("lc-quiet-btn").set_enabled(not view.running)


def file_label(f: FileState, on_got: Callable[[], Awaitable[None]]) -> None:
    if f.modified:
        when = f.modified.strftime("%Y-%m-%d %H:%M")
    else:
        when = "not downloaded" if f.placeholder else "missing"
    with ui.row().classes("items-center gap-1 no-wrap"):
        shown = ui.label(f"{f.path} ({when})")
        if f.modified:
            shown.classes("cursor-pointer").on("click", lambda: open_path(f.resolved))
        else:
            shown.classes("text-negative")
        if f.placeholder:
            get_button("Get", run_get, [[f.resolved]], on_got)


def log_panel(view: PrepareView) -> None:
    session = view.session
    tracked = {"name": None, "lines": 0}

    def current() -> str | None:
        return session.current if view.running and session.current else view.shown

    with panel("Log") as tools:
        log = ui.log().classes("lc-log w-full h-72")
    with tools:
        title = ui.label(NO_LOG).classes("lc-note")
        copy = (
            ui.button(
                "Copy log",
                icon="content_copy",
                on_click=lambda: ui.clipboard.write("\n".join(session.runs[current()].log)),
            )
            .props("flat dense no-caps")
            .classes("lc-quiet-btn")
        )
        copy.visible = False

    def poll() -> None:
        name = current()
        if name != tracked["name"]:
            log.clear()
            tracked.update(name=name, lines=0)
            title.set_text(name or NO_LOG)
            copy.visible = name is not None
        found = session.runs.get(name) if name else None
        if found is None:
            return
        for line in found.log[tracked["lines"] :]:
            log.push(line)
        tracked["lines"] = len(found.log)

    poll()
    ui.timer(POLL_SECONDS, poll)


def draft_panel(result: CatalogResult | None, on_saved: Callable[[], Awaitable[None]]) -> None:
    with panel(
        "Draft a cleaning step",
        "A language model writes a script that turns a raw export into a dataset's file",
    ):
        if result is None or result.project is None:
            note("Open a project that reads without errors to draft a step.")
            return
        if not common.model_set():
            note("Set a language model on the Settings page to draft a cleaning script.")
            return
        project = result.project
        names = [d.name for d in project.config.datasets if d.source == "csv" and d.path]
        if not names:
            note("No dataset reads a CSV file yet; add one first.")
            return
        root = project.root
        steps = {n: cleaning_step(project, n) for n in names}
        first = next((n for n in names if steps[n] is None), names[0])

        def raw_for(name: str) -> str:
            step = steps[name]
            return (raw_of(step) if step else None) or ""

        note(
            "Choose the dataset and the raw export it comes from. Nothing is saved until you have "
            "read the script; it then joins the steps above as clean_<dataset>, writing the "
            "dataset's file and never the export. " + sent_text(project.config.llm.raw_data)
        )
        with ui.row().classes("w-full items-start gap-2"):
            dataset = (
                ui.select(
                    names,
                    value=first,
                    label="Dataset",
                    with_input=True,
                    on_change=lambda e: raw.set_value(raw_for(e.value)),
                )
                .props("outlined dense")
                .classes("w-72")
            )
            raw = path_input("Raw export", raw_for(first), "In the project folder, such as raw/")

            async def choose() -> None:
                found = await choose_path(file_types=("CSV files (*.csv;*.tsv;*.txt)",), start=root)
                if found:
                    raw.set_value(posix_str(portable_path(found, root)))

            ui.button("Choose", on_click=choose).props("flat no-caps")
            language = ui.toggle(LANGUAGE_NAMES, value="r").props("dense no-caps")
            button = ui.button("Draft", icon="edit_note", on_click=lambda: draft())
        status = ui.label().classes("lc-note")

        async def draft() -> None:
            chosen = (raw.value or "").strip().strip('"')
            if not chosen or not (root / chosen).is_file():
                status.set_text("Choose a raw export inside the project folder.")
                return
            button.disable()
            status.set_text("Reading the export and drafting the script.")
            try:
                found = await computed(
                    run_cleaning_draft,
                    result,
                    dataset.value,
                    chosen,
                    language.value,
                    *common.llm_choice(),
                )
            except LabCatalogError as err:
                status.set_text(str(err))
                return
            finally:
                button.enable()
            status.set_text("")
            review(found, root, on_saved)
