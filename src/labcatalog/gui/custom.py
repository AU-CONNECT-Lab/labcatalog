import base64
import io
import subprocess
from dataclasses import dataclass, field

import pandas as pd
from nicegui import ui

from labcatalog.ai.custom import LANGUAGES, AnalysisDraft
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import analysis as page
from labcatalog.gui import analysis_tables, common, missing, paper, theme
from labcatalog.gui.common import caption, computed, note, panel
from labcatalog.pipeline import CatalogResult, run_analysis_draft, run_analysis_fix
from labcatalog.processes import end_tree
from labcatalog.stats import analysis
from labcatalog.stats.analysis_script import DATA_FILE
from labcatalog.stats.custom import SCRIPT, Ran, analysis_frame, columns_text, run_script

LANGUAGE_NAMES = {key: lang.name for key, lang in LANGUAGES.items()}
EDITOR_LANGUAGES = {"r": "R", "python": "Python"}
IMAGES = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
SENT = (
    "Draft sends what you write here, with the chosen columns' names, labels, answer options "
    "and how many people have a value, to the model set on the Settings page; never the data. "
    "Paste a few rows into the box yourself if the model needs to see them."
)


@dataclass
class Choices:
    variables: list[str] = field(default_factory=list)
    wanted: str = ""
    language: str = "r"
    script: str = ""


@dataclass
class Running:
    process: subprocess.Popen | None = None
    # The columns as last sent or run, so a fix describes the data the script ran on.
    columns: str = ""
    ran: Ran | None = None


def render(result: CatalogResult, sample: analysis.Sample, view, choices: dict[str, str]) -> None:
    chosen = view.custom
    chosen.variables = [k for k in chosen.variables if k in choices]
    running = Running()

    async def columns() -> tuple[pd.DataFrame, str]:
        frame, variables, _ = await computed(analysis_frame, result, sample, chosen.variables)
        running.columns = columns_text(result, sample, frame, variables)
        return frame, running.columns

    async def draft() -> None:
        if not chosen.wanted.strip():
            status.set_text("Say first what analysis you want.")
            return
        draft_button.disable()
        status.set_text("Drafting the script.")
        try:
            _, text = await columns()
            found = await computed(
                run_analysis_draft,
                text,
                chosen.wanted,
                chosen.language,
                DATA_FILE,
                *common.llm_choice(),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        finally:
            draft_button.enable()
        status.set_text(made_by(found))
        use(found)

    def use(found: AnalysisDraft) -> None:
        chosen.script = found.script
        editor.set_value(found.script)
        notes.clear()
        with notes:
            for line in found.changes:
                note(f"Changed: {line}")
            for line in found.notes:
                note(f"To check: {line}")

    async def run_it() -> None:
        if not chosen.script.strip():
            status.set_text("Draft or write a script first.")
            return
        run_button.disable()
        stop_button.set_visibility(True)
        status.set_text("Running the script.")
        script, language = chosen.script, chosen.language
        try:
            frame, _ = await columns()
            ran = await computed(
                run_script,
                language,
                script,
                frame,
                analysis_tables.rscript(),
                lambda process: setattr(running, "process", process),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        finally:
            running.process = None
            run_button.enable()
            stop_button.set_visibility(False)
        running.ran = ran
        status.set_text("" if ran.ok else "The script stopped with an error; see its output.")
        fix_button.set_visibility(not ran.ok and common.model_set())
        show(ran, frame, script, language)

    def stop() -> None:
        if running.process is not None:
            end_tree(running.process)

    def show(ran: Ran, frame: pd.DataFrame, script: str, language: str) -> None:
        shown.clear()
        with shown:
            if ran.output:
                caption("Output")
                ui.code(ran.output, language="plaintext").classes("w-full")
            for name, content in ran.files.items():
                suffix = name[name.rfind(".") :].lower() if "." in name else ""
                if suffix in IMAGES:
                    caption(name)
                    encoded = base64.b64encode(content).decode()
                    ui.image(f"data:{IMAGES[suffix]};base64,{encoded}").classes("max-w-full")
                elif suffix == ".csv":
                    caption(name)
                    table = pd.read_csv(io.BytesIO(content))
                    ui.table.from_pandas(table.round(common.decimals())).props(
                        "dense flat"
                    ).classes("w-full")
                else:
                    note(f"It also wrote {name}.")
            texts = {
                DATA_FILE: frame.to_csv(index=False),
                SCRIPT[language]: script,
                "output.txt": ran.output,
            }
            paper.save_button(result, "custom", texts=texts, blobs=ran.files)

    async def fix() -> None:
        fix_button.disable()
        status.set_text("Asking the model to fix the script.")
        try:
            found = await computed(
                run_analysis_fix,
                running.columns,
                chosen.wanted,
                chosen.language,
                DATA_FILE,
                chosen.script,
                running.ran.output,
                *common.llm_choice(),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        finally:
            fix_button.enable()
        status.set_text("")
        review(found)

    def review(found: AnalysisDraft) -> None:
        def take() -> None:
            use(found)
            dialog.close()

        with ui.dialog() as dialog, ui.card().classes("w-[60rem] max-w-full gap-3"):
            ui.label("The revised script").classes("text-lg")
            note(made_by(found))
            for line in found.changes:
                ui.label(line)
            for line in found.notes:
                note(f"To check: {line}")
            ui.code(found.diff(), language="diff").classes("w-full")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Use it", icon="check", on_click=take).props("no-caps")
        dialog.open()

    def set_language(value: str) -> None:
        chosen.language = value
        editor.language = EDITOR_LANGUAGES[value]

    def set_script(value: str) -> None:
        chosen.script = value

    with panel("Custom analysis", "Any analysis, in a script you can read and change"):
        note(SENT)
        if missing.imputing(result, view):
            note("The script reads the data as they are, without the imputations.")
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            picked = (
                ui.select(
                    choices,
                    multiple=True,
                    value=chosen.variables,
                    label="Variables",
                    with_input=True,
                    on_change=lambda e: setattr(chosen, "variables", e.value or []),
                )
                .props("dense outlined use-chips")
                .classes("grow")
            )
            page.pick_menu(
                picked, page.views.menu_groups(result, view.datasets, page.variables(view))
            )
        ui.textarea(
            "The analysis",
            placeholder="For example: does the parent's stress predict the child's sleep "
            "problems a year later, with the child's age as a covariate?",
        ).bind_value(chosen, "wanted").props("outlined autogrow").classes("w-full")
        with ui.row().classes("items-center gap-3"):
            ui.toggle(
                LANGUAGE_NAMES, value=chosen.language, on_change=lambda e: set_language(e.value)
            ).props("dense no-caps")
            draft_button = ui.button("Draft", icon="edit_note", on_click=draft).props("no-caps")
            if not common.model_set():
                draft_button.disable()
                draft_button.tooltip("Set a language model on the Settings page")
        status = ui.label().classes("lc-note")
        notes = ui.column().classes("w-full gap-1")
        editor = (
            ui.codemirror(
                chosen.script,
                language=EDITOR_LANGUAGES[chosen.language],
                line_wrapping=True,
                theme=theme.codemirror_theme(),
                on_change=lambda e: set_script(e.value),
            )
            .classes("w-full")
            .style("height: 40vh")
        )
        with ui.row().classes("lc-actions items-center gap-2"):
            run_button = ui.button("Run", icon="play_arrow", on_click=run_it).props("no-caps")
            stop_button = ui.button("Stop", icon="stop", on_click=stop).props("flat no-caps")
            stop_button.set_visibility(False)
            fix_button = ui.button("Ask the model to fix it", icon="build", on_click=fix).props(
                "flat no-caps"
            )
            fix_button.set_visibility(False)
        shown = ui.column().classes("w-full gap-2")


def made_by(found: AnalysisDraft) -> str:
    meta = found.meta
    return (
        f"A draft by {meta.model} in {meta.latency_ms / 1000:.0f} s, {meta.input_tokens} tokens "
        f"in and {meta.output_tokens} out. Read it before running it."
    )
