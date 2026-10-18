from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import run, ui

from labcatalog.ai.cleaning import (
    LANGUAGES,
    RAW_ROWS,
    ROWS,
    CleaningDraft,
    language_of,
    save_draft,
)
from labcatalog.gui.common import caption, note


def sent_text(raw_data: str) -> str:
    what = f"its first {RAW_ROWS} lines" if raw_data == ROWS else "each column's values"
    return (
        f"Sends the raw file's column names and {what}, as the project sets on the Settings page, "
        "with the dataset's columns, answer options and missing codes."
    )


def review(draft: CleaningDraft, root: Path, on_saved: Callable[[], Awaitable[None]]) -> None:
    meta = draft.meta
    path = root / draft.script_path
    if draft.step is None:
        action = f"Save {draft.script_path}"
    else:
        verb = "Replace" if path.exists() else "Save"
        action = f"{verb} {draft.script_path} and the step {draft.step.name}"

    async def save() -> None:
        await run.io_bound(save_draft, root, draft)
        dialog.close()
        if draft.step is None:
            ui.notify("Saved; run the step again to rebuild the file")
        await on_saved()

    with ui.dialog() as dialog, ui.card().classes("w-[60rem] max-w-full gap-3"):
        ui.label(draft.script_path).classes("text-lg")
        note(
            f"A draft by {meta.model} in {meta.latency_ms / 1000:.0f} s, {meta.input_tokens} "
            f"tokens in and {meta.output_tokens} out. Read it before saving; nothing is written "
            "until you do."
        )
        if draft.changes:
            caption("What changed")
            for line in draft.changes:
                ui.label(line)
        if draft.notes:
            caption("To check")
            for line in draft.notes:
                ui.label(line)
        if draft.previous is None:
            if draft.step is not None:
                note(f"The step runs: {draft.step.run}")
            ui.code(draft.script, language=language_of(draft.script_path)).classes("w-full")
        else:
            ui.code(draft.diff(), language="diff").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button(action, icon="save", on_click=save).props("no-caps")
    dialog.open()


LANGUAGE_NAMES = {key: lang.name for key, lang in LANGUAGES.items()}
