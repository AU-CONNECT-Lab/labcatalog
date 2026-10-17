import difflib
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

import webview
from nicegui import app, ui

from labcatalog.charts import views
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, note
from labcatalog.metadata import changes, new_dataset
from labcatalog.pipeline import CatalogResult

DATA_FILES = "Data files (*.csv)"
REPEAT = "repeat"
BLANK = "blank"


def open_wizard(
    result: CatalogResult, on_done: Callable[[str], Awaitable[None]], study: str | None = None
) -> None:
    project = result.project
    config = project.config
    names = new_dataset.templates(project)
    # A study with nothing to repeat yet starts from nothing.
    if study is not None or not names:
        start = BLANK
        first = new_dataset.suggest_blank(project, study or next(iter(config.studies)))
    else:
        start = REPEAT
        first = new_dataset.suggest(project, names[-1])
    state: dict = {
        "source": None,
        "placement": None,
        "created": [],
        "rows": [],
        "changes": [],
        "columns": [],
        "id_column": None,
        "date_column": None,
    }

    def cleanup() -> None:
        new_dataset.remove(project, state["created"])
        state["created"] = []

    def cancel() -> None:
        cleanup()
        dialog.close()

    def suggest(template: str) -> None:
        draft = new_dataset.suggest(project, template)
        name.value, wave.value = draft.name, draft.wave

    def switch(mode: str) -> None:
        repeating.visible, describing.visible = mode == REPEAT, mode == BLANK
        if mode == REPEAT:
            suggest(template.value)
        else:
            name.value, wave.value = "", new_dataset.suggest_blank(project, own_study.value).wave

    def blank() -> bool:
        return mode.value == BLANK

    def draft() -> new_dataset.Draft:
        described = None
        if blank():
            described = new_dataset.Blank(
                own_study.value,
                modality.value,
                reporter.value,
                state["id_column"],
                state["date_column"] or None,
            )
        return new_dataset.Draft(
            "" if blank() else template.value,
            (name.value or "").strip(),
            (wave.value or "").strip(),
            date.fromisoformat((as_of.value or "").strip()),
            described,
        )

    def start_next() -> None:
        try:
            new_dataset.check_draft(project, draft())
        except ValueError:
            start_status.set_text("Data as of: a date such as 2026-10-16")
            return
        except LabCatalogError as err:
            start_status.set_text(str(err))
            return
        start_status.set_text("")
        stepper.next()

    async def choose() -> None:
        selection = await app.native.main_window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=(DATA_FILES,)
        )
        if selection:
            state["source"] = Path(selection[0])
            chosen.set_text(str(state["source"]))

    async def file_next() -> None:
        if state["source"] is None:
            file_status.set_text("Choose the data file first.")
            return
        cleanup()
        log.clear()
        try:
            placement = new_dataset.place(project, draft(), state["source"])
        except LabCatalogError as err:
            file_status.set_text(str(err))
            return
        state["placement"] = placement
        file_status.set_text(
            f"Copying it to {placement.copy_to}"
            + (f" and running {placement.step.name}" if placement.step else "")
        )
        brought = await computed(new_dataset.bring_in, project, state["source"], placement)
        state["created"] = brought.created
        if brought.run is not None and brought.run.exit_code != 0:
            file_status.set_text(
                f"{placement.step.name} stopped with an error; show this to whoever looks after "
                "the cleaning scripts."
            )
            with log:
                ui.code("\n".join(brought.run.log), language=None).classes("w-full")
            return
        try:
            dataset = new_dataset.dataset_config(project, draft(), placement)
            if blank():
                found = await computed(new_dataset.file_columns, project, dataset)
                usual = config.defaults.id_column
                state["columns"] = found
                state["id_column"] = usual if usual in found else found[0]
                state["date_column"] = next((c for c in found if "date" in c.lower()), "")
            state["rows"] = await computed(new_dataset.match_columns, project, dataset)
        except LabCatalogError as err:
            file_status.set_text(str(err))
            return
        file_status.set_text("")
        columns.refresh()
        stepper.next()

    @ui.refreshable
    def columns() -> None:
        rows = state["rows"]
        if not rows:
            return
        if blank():
            with ui.row().classes("gap-3"):
                ui.select(
                    state["columns"],
                    value=state["id_column"],
                    label="ID column",
                    on_change=lambda e: state.update(id_column=e.value),
                ).classes("w-56")
                ui.select(
                    ["", *state["columns"]],
                    value=state["date_column"],
                    label="Date column (optional)",
                    on_change=lambda e: state.update(date_column=e.value),
                ).classes("w-56")
        found = new_dataset.coverage(project, draft().template, rows)
        labels = views.instrument_names(result)
        with ui.row().classes("gap-2"):
            for instrument_id, (n, total) in found.items():
                kind = "lc-ok" if n == total else "lc-warn" if n else "lc-bad"
                ui.label(f"{labels[instrument_id]}: {n} of {total} items").classes(
                    f"lc-pill {kind}"
                )
        left = sum(not r["instrument"] for r in rows)
        note(
            f"{left} of {len(rows)} columns are not items of a catalogued instrument, such as the "
            "ID and dates; fill in instrument and item for any that are. Columns of an "
            "instrument the catalog does not have yet come in through the Import page later."
        )
        state["grid"] = (
            ui.aggrid(
                {
                    "columnDefs": [
                        {"field": "column", "headerName": "Column", "flex": 2},
                        {
                            "field": "instrument",
                            "headerName": "Instrument",
                            "editable": True,
                            "cellEditor": "agSelectCellEditor",
                            "cellEditorParams": {"values": ["", *project.instruments]},
                            "flex": 2,
                        },
                        {"field": "item", "headerName": "Item", "editable": True, "flex": 1},
                    ],
                    "rowData": rows,
                    "stopEditingWhenCellsLoseFocus": True,
                }
            )
            .classes("w-full")
            .style("height: 45vh")
        )

    async def columns_next() -> None:
        rows = await state["grid"].get_client_data()
        rows = [{k: (r.get(k) or "") for k in ("column", "instrument", "item")} for r in rows]
        problems = new_dataset.check_rows(project, rows)
        if problems:
            columns_status.set_text("; ".join(problems))
            return
        state["rows"] = rows
        try:
            found = new_dataset.changes(project, draft(), state["placement"], rows)
        except LabCatalogError as err:
            columns_status.set_text(str(err))
            return
        issues = changes.check(project, found)
        if issues:
            columns_status.set_text("; ".join(str(i) for i in issues))
            return
        columns_status.set_text("")
        state["changes"] = found
        review.refresh()
        stepper.next()

    @ui.refreshable
    def review() -> None:
        placement = state["placement"]
        if placement is None:
            return
        note(f"Copied the data to {placement.copy_to}.")
        if placement.step is not None:
            note(
                f"Cleaned with a new prepare step, {placement.step.name}, the same as the one "
                f"for {template.value}: {placement.step.run}"
            )
        if new_dataset.is_new_wave(project, draft()):
            note(
                f"Wave {wave.value} is new, so it is added to the study without dates; fill in "
                "its start and end on the Studies page."
            )
        note("Adding the dataset changes these files; each line with + is new.")
        for change in state["changes"]:
            before = change.opened.text if change.opened else ""
            lines = difflib.unified_diff(
                before.splitlines(), change.text.splitlines(), lineterm="", n=0
            )
            shown = [line for line in lines if line[:1] in "+-" and line[:3] not in ("+++", "---")]
            ui.label(change.path + ("" if change.opened else " (new)")).classes("font-medium")
            ui.code("\n".join(shown), language="diff").classes("w-full lc-wrap")

    async def finish() -> None:
        try:
            changes.write(project, state["changes"])
        except LabCatalogError as err:
            review_status.set_text(str(err))
            return
        # Written now, so closing the window must no longer remove them.
        state["created"] = []
        dialog.close()
        await on_done(draft().name)

    with ui.dialog().props("persistent") as dialog, ui.card().classes("w-[64rem] max-w-full"):
        ui.label("Add a dataset").classes("text-lg font-medium")
        with ui.stepper().props("flat animated").classes("w-full") as stepper:
            with ui.step("Start from"):
                mode = ui.toggle(
                    {REPEAT: "Repeat a dataset", BLANK: "A new kind of file"},
                    value=start,
                    on_change=lambda e: switch(e.value),
                ).props("dense no-caps")
                mode.visible = bool(names)
                with ui.column().classes("gap-2") as repeating:
                    note(
                        "Pick the dataset this one repeats, usually the same file from the last "
                        "wave. The new one takes its modality, study, reporter, ID and date "
                        "columns, and its cleaning step if it has one."
                    )
                    template = ui.select(
                        {n: views.dataset_label(result, n) for n in names},
                        value=names[-1] if names else None,
                        label="Same as",
                        on_change=lambda e: suggest(e.value),
                    ).classes("w-96")
                with ui.column().classes("gap-2") as describing:
                    note(
                        "Say what the file is: the first dataset of a study, or a kind of file "
                        "the project has not had before. The ID and date columns are chosen "
                        "after the file. The file is copied into data/ as it is, with no "
                        "cleaning step."
                    )
                    with ui.row().classes("gap-3"):
                        own_study = ui.select(
                            {s: c.label or s for s, c in config.studies.items()},
                            value=first.blank.study if first.blank else next(iter(config.studies)),
                            label="Study",
                            on_change=lambda e: wave.set_value(
                                new_dataset.suggest_blank(project, e.value).wave
                            ),
                        ).classes("w-64")
                        modality = ui.select(
                            {m: config.vocab.modality_label(m) for m in config.vocab.modalities},
                            value=config.vocab.modalities[0],
                            label="Modality",
                        ).classes("w-48")
                        reporter = ui.select(
                            config.vocab.reporters,
                            value=(config.vocab.reporters or [None])[0],
                            label="Reporter",
                        ).classes("w-48")
                repeating.visible, describing.visible = start == REPEAT, start == BLANK
                with ui.row().classes("gap-3"):
                    name = ui.input("Name", value=first.name).classes("w-56")
                    wave = ui.input("Wave", value=first.wave).classes("w-24")
                    as_of = ui.input("Data as of", value=first.snapshot_date.isoformat()).classes(
                        "w-40"
                    )
                start_status = ui.label().classes("lc-bad-text")
                with ui.stepper_navigation():
                    ui.button("Next", on_click=start_next)
                    ui.button("Cancel", on_click=cancel).props("flat")
            with ui.step("Data file"):
                note(
                    "Choose the file as it came from the survey platform or the lab's pipeline. "
                    "labcatalog copies it into the project; the file you chose stays where it is."
                )
                with ui.row().classes("items-center gap-3"):
                    ui.button("Choose the file", icon="upload_file", on_click=choose).props(
                        "flat"
                    ).classes("lc-quiet-btn")
                    chosen = ui.label().classes("lc-note")
                file_status = ui.label().classes("lc-note")
                log = ui.column().classes("w-full")
                with ui.stepper_navigation():
                    ui.button("Next", on_click=file_next)
                    ui.button("Back", on_click=stepper.previous).props("flat")
                    ui.button("Cancel", on_click=cancel).props("flat")
            with ui.step("Columns"):
                columns()
                columns_status = ui.label().classes("lc-bad-text")
                with ui.stepper_navigation():
                    ui.button("Next", on_click=columns_next)
                    ui.button("Back", on_click=stepper.previous).props("flat")
                    ui.button("Cancel", on_click=cancel).props("flat")
            with ui.step("Check and add"):
                review()
                review_status = ui.label().classes("lc-bad-text")
                with ui.stepper_navigation():
                    ui.button("Add the dataset", icon="check", on_click=finish)
                    ui.button("Back", on_click=stepper.previous).props("flat")
                    ui.button("Cancel", on_click=cancel).props("flat")
    # Closing the window halfway leaves no copied files behind.
    ui.context.client.on_disconnect(cleanup)
    dialog.open()
