from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import run, ui

from labcatalog.ai.cleaning import RAW_ROWS, ROWS
from labcatalog.ai.features import SummaryDraft, save_summary
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common
from labcatalog.gui.cleaning import LANGUAGE_NAMES
from labcatalog.gui.common import caption, computed, note
from labcatalog.metadata.scripts import language_of
from labcatalog.pipeline import CatalogResult, run_summary_draft


def summary_panel(result: CatalogResult | None, on_saved: Callable[[], Awaitable[None]]) -> None:
    if result is None or result.project is None:
        note("Open a project that reads without errors to draft a step.")
        return
    if not common.model_set():
        note("Set a language model on the Settings page to draft a summary script.")
        return
    project = result.project
    folders = [d.name for d in project.config.datasets if d.source == "folder"]
    if not folders:
        note(
            "Add the files first as a folder dataset (Datasets, Add a dataset), such as a task's "
            "trial files with one file per person."
        )
        return
    what = (
        f"the first {RAW_ROWS} lines of its largest file"
        if project.config.llm.raw_data == ROWS
        else "each column's values across its files"
    )
    note(
        "For a folder dataset with one file per person, such as a computer task's trials: a "
        "language model writes the features() of an extract script, which turns each person's "
        "file into their row of measures, and drafts the instrument those measures make up. "
        f"Sends the column names and {what}, as the Settings page sets, with the measures you "
        "ask for. Nothing is saved until you have read the draft."
    )
    with ui.row().classes("w-full items-start gap-2"):
        files = (
            ui.select(folders, value=folders[0], label="Files", with_input=True)
            .props("outlined dense")
            .classes("w-60")
        )
        name = ui.input("Dataset it writes", placeholder="nback_w2").props("outlined dense")
        instrument = ui.input("Instrument ID", placeholder="nback").props("outlined dense")
        language = ui.toggle(LANGUAGE_NAMES, value="r").props("dense no-caps")
    wanted = (
        ui.textarea(
            "Measures to compute",
            placeholder="Accuracy, mean response time of correct trials and d' for each block",
        )
        .props("outlined dense autogrow")
        .classes("w-full")
    )
    with ui.row().classes("w-full items-center gap-2"):
        button = ui.button("Draft", icon="edit_note", on_click=lambda: draft())
        status = ui.label().classes("lc-note")

    async def draft() -> None:
        button.disable()
        status.set_text("Reading one person's file and drafting the script.")
        try:
            found = await computed(
                run_summary_draft,
                result,
                files.value,
                (name.value or "").strip(),
                (instrument.value or "").strip(),
                wanted.value or "",
                language.value,
                *common.llm_choice(),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        finally:
            button.enable()
        status.set_text("")
        review(found, project.root, on_saved)


def review(draft: SummaryDraft, root: Path, on_saved: Callable[[], Awaitable[None]]) -> None:
    meta = draft.meta
    replaced = (root / draft.instrument_path).exists()

    async def save() -> None:
        await run.io_bound(save_summary, root, draft)
        dialog.close()
        ui.notify(
            f"Saved; run {draft.step.name}, check {draft.instrument_path} on the Edit page and "
            f"move it to instruments, then add {draft.step.outputs[0]} as a dataset",
            multi_line=True,
        )
        await on_saved()

    with ui.dialog() as dialog, ui.card().classes("w-[60rem] max-w-full gap-3"):
        ui.label(draft.script_path).classes("text-lg")
        note(
            f"A draft by {meta.model} in {meta.latency_ms / 1000:.0f} s, {meta.input_tokens} "
            f"tokens in and {meta.output_tokens} out, from {draft.shown}. Read it before saving; "
            "nothing is written until you do."
        )
        if draft.notes:
            caption("To check")
            for line in draft.notes:
                ui.label(line)
        note(f"The step runs: {draft.step.run}")
        ui.code(draft.script, language=language_of(draft.script_path)).classes("w-full")
        caption(draft.instrument_path + (", replacing the draft there" if replaced else ""))
        ui.code(draft.instrument, language="yaml").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button(
                f"Save the script, the step {draft.step.name} and the draft",
                icon="save",
                on_click=save,
            ).props("no-caps")
    dialog.open()
