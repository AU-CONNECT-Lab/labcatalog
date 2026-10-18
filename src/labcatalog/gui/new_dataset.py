import difflib
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

import webview
from nicegui import app, ui

from labcatalog.charts import views
from labcatalog.config import dataset_by_name
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, note, path_input, show_status
from labcatalog.metadata import changes, new_dataset
from labcatalog.paths import expand_path, stored_path
from labcatalog.pipeline import CatalogResult

DATA_FILES = "Data files (*.csv)"
REPEAT = "repeat"
BLANK = "blank"
TABLE = "table"
FOLDER = "folder"
DATA_STEP = "Data"
CHECK_STEP = "Check and add"


def open_wizard(
    result: CatalogResult,
    on_done: Callable[[str], Awaitable[None]],
    study: str | None = None,
    repeat: tuple[str, str] | None = None,
) -> None:
    # repeat is (template, wave), to start with both filled in.
    project = result.project
    config = project.config
    names = new_dataset.templates(project)
    # A study with nothing to repeat yet starts from nothing.
    if repeat is not None:
        start = REPEAT
        first = new_dataset.suggest(project, *repeat)
    elif study is not None or not names:
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
        "wave_column": None,
        "paths": [],
        "prefilled": None,
        "wave_dates": (None, None),
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

    def folder() -> bool:
        if blank():
            return kind.value == FOLDER
        return dataset_by_name(config, template.value).source == FOLDER

    def long() -> bool:
        return not blank() and bool(dataset_by_name(config, template.value).wave_column)

    def draft() -> new_dataset.Draft:
        described = None
        if blank():
            described = new_dataset.Blank(
                own_study.value,
                modality.value,
                reporter.value,
                state["id_column"],
                state["date_column"] or None,
                state["wave_column"] or None,
            )
        return new_dataset.Draft(
            "" if blank() else template.value,
            (name.value or "").strip(),
            (wave.value or "").strip(),
            date.fromisoformat((as_of.value or "").strip()),
            described,
            (files.value or "").strip() if folder() else None,
            *state["wave_dates"],
        )

    async def prefill_dates() -> None:
        # The new wave starts on the data's first date; its end stays open while it collects.
        new = new_dataset.is_new_wave(project, draft())
        dates_box.visible = new
        if not new:
            state["wave_dates"] = (None, None)
            return
        dataset = new_dataset.dataset_config(project, draft(), state["placement"])
        first_day, last_day = await computed(new_dataset.date_range, project, dataset)
        state["wave_dates"] = (first_day, None)
        starts.set_value(first_day.isoformat() if first_day else "")
        ends.set_value("")
        last_note.set_text(
            f"The data run to {last_day.isoformat()}. Leave the end empty while the wave is "
            "still collecting."
            if last_day
            else "Leave the end empty while the wave is still collecting."
        )

    def dates_changed() -> None:
        try:
            state["wave_dates"] = tuple(
                date.fromisoformat(box.value.strip()) if (box.value or "").strip() else None
                for box in (starts, ends)
            )
        except ValueError:
            review_status.set_text("Wave dates: a date such as 2026-10-16, or empty")
            return
        rows = [] if folder() else state["rows"]
        try:
            state["changes"] = new_dataset.changes(project, draft(), state["placement"], rows)
        except LabCatalogError as err:
            review_status.set_text(str(err))
            return
        review_status.set_text("")
        review.refresh()

    async def prefill_folder() -> None:
        # From the dataset it repeats, kept once the person has changed it for this template and wave.
        chosen_wave = (wave.value or "").strip()
        if state["prefilled"] == (template.value, chosen_wave):
            return
        state["prefilled"] = (template.value, chosen_wave)
        folder_path.set_value(dataset_by_name(config, template.value).path)
        files.set_value(new_dataset.suggest_files(project, template.value, chosen_wave))
        await scan_folder()

    async def start_next() -> None:
        try:
            new_dataset.check_draft(project, draft())
        except ValueError:
            start_status.set_text("Data as of: a date such as 2026-10-16")
            return
        except LabCatalogError as err:
            start_status.set_text(str(err))
            return
        start_status.set_text("")
        table_box.visible = not folder() and not long()
        folder_box.visible, long_box.visible = folder(), long()
        if folder() and not blank():
            await prefill_folder()
        if long():
            await show_rows(rows_status)
        stepper.next()

    async def choose() -> None:
        selection = await app.native.main_window.create_file_dialog(
            webview.FileDialog.OPEN, file_types=(DATA_FILES,)
        )
        if selection:
            state["source"] = Path(selection[0])
            chosen.set_text(str(state["source"]))

    async def choose_folder() -> None:
        selection = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
        if selection:
            folder_path.set_value(selection[0])
            await scan_folder()

    def typed_folder() -> Path | None:
        text = (folder_path.value or "").strip()
        return expand_path(text, project.root) if text else None

    async def scan_folder() -> None:
        state["paths"] = []
        found = typed_folder()
        if found and found.is_dir():
            state["paths"] = await computed(new_dataset.folder_files, found)
        # As typed, so ~ and environment variables stay in labcatalog.yaml.
        text = (folder_path.value or "").strip()
        state["source"] = stored_path(text) if text else None
        preview.refresh()

    @ui.refreshable
    def preview() -> None:
        found = typed_folder()
        if found is None:
            return
        if not found.is_dir():
            ui.label("No folder there.").classes("lc-bad-text")
            return
        rule = (files.value or "").strip()
        if not rule:
            note(f"{len(state['paths'])} files in the folder. Now say which ones to count.")
            return
        try:
            seen = new_dataset.preview_folder(state["paths"], rule)
        except LabCatalogError as err:
            ui.label(str(err)).classes("lc-bad-text")
            return
        status = "lc-ok" if seen.people else "lc-warn"
        ui.label(f"{seen.files} files of {seen.people} people match").classes(f"lc-status {status}")
        if seen.unmatched:
            shown = ", ".join(seen.unmatched[:5])
            more = f" and {len(seen.unmatched) - 5} more" if len(seen.unmatched) > 5 else ""
            note(f"Not counted ({len(seen.unmatched)}): {shown}{more}")

    async def show_rows(status: ui.label) -> bool:
        # The rows the new dataset will read, so a wave written differently shows up here.
        try:
            placement = state["placement"] if blank() else new_dataset.place(project, draft(), None)
            dataset = new_dataset.dataset_config(project, draft(), placement)
            seen = await computed(new_dataset.wave_rows, project, dataset)
        except LabCatalogError as err:
            show_status(status, str(err), "bad")
            return False
        found = f"of {dataset.path} have {dataset.wave_column} {dataset.wave}"
        if not seen.rows:
            waves = ", ".join(seen.waves) or "none"
            show_status(status, f"No rows {found}; the waves in it are {waves}.", "warn")
            return False
        show_status(status, f"{seen.rows} rows {found}", "ok")
        state["placement"] = placement
        return True

    async def long_next() -> None:
        if not await show_rows(rows_status):
            return
        state["rows"] = new_dataset.template_rows(project, template.value)
        columns.refresh()
        stepper.next()

    async def folder_next() -> None:
        found = typed_folder()
        if found is None or not found.is_dir():
            file_status.set_text("Choose the folder first.")
            return
        try:
            seen = new_dataset.preview_folder(state["paths"], (files.value or "").strip())
            if not seen.people:
                raise LabCatalogError("No file matches; check the files rule")
            state["placement"] = new_dataset.place(project, draft(), state["source"])
            await prefill_dates()
            found = new_dataset.changes(project, draft(), state["placement"], [])
        except LabCatalogError as err:
            file_status.set_text(str(err))
            return
        issues = changes.check(project, found)
        if issues:
            file_status.set_text("; ".join(str(i) for i in issues))
            return
        file_status.set_text("")
        state["changes"] = found
        review.refresh()
        # A folder has no columns to match.
        stepper.set_value(CHECK_STEP)

    def check_back() -> None:
        if folder():
            stepper.set_value(DATA_STEP)
        else:
            stepper.previous()

    async def file_next() -> None:
        if folder():
            await folder_next()
            return
        if long():
            await long_next()
            return
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
                state["wave_column"] = ""
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
                ui.select(
                    ["", *state["columns"]],
                    value=state["wave_column"],
                    label="Wave column (optional)",
                    on_change=pick_wave_column,
                ).classes("w-56")
            note(
                "Pick a wave column when the file holds several waves, one row per person per "
                f"wave; this dataset then reads the rows of wave {wave.value} only."
            )
            state["wave_status"] = ui.label()
            state["wave_status"].visible = False
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

    async def pick_wave_column(event) -> None:
        state["wave_column"] = event.value
        if not event.value:
            state["wave_status"].visible = False
            return
        await show_rows(state["wave_status"])

    async def columns_next() -> None:
        if blank() and state["wave_column"] and not await show_rows(state["wave_status"]):
            columns_status.set_text("No rows of this wave; pick another wave column or none")
            return
        rows = await state["grid"].get_client_data()
        rows = [{k: (r.get(k) or "") for k in ("column", "instrument", "item")} for r in rows]
        problems = new_dataset.check_rows(project, rows)
        if problems:
            columns_status.set_text("; ".join(problems))
            return
        state["rows"] = rows
        try:
            await prefill_dates()
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
        if long():
            column = dataset_by_name(config, template.value).wave_column
            note(
                f"Reads the rows of {placement.data_path} where {column} is {wave.value}; "
                "nothing is copied."
            )
        elif placement.copy_to is None:
            note(f"Reads the files where they are, in {placement.data_path}; nothing is copied.")
        else:
            note(f"Copied the data to {placement.copy_to}.")
        if placement.step is not None:
            note(
                f"Cleaned with a new prepare step, {placement.step.name}, the same as the one "
                f"for {template.value}: {placement.step.run}"
            )
        if new_dataset.is_new_wave(project, draft()):
            note(f"Wave {wave.value} is new, so it is added to the study with the dates above.")
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
                        "columns, and its cleaning step if it has one. A folder of files takes its "
                        "folder and files rule, with the wave changed where the rule names it. A "
                        "file with a wave column, which holds every wave, is read again for the "
                        "new wave."
                    )
                    template = ui.select(
                        {n: views.dataset_label(result, n) for n in names},
                        value=first.template or (names[-1] if names else None),
                        label="Same as",
                        on_change=lambda e: suggest(e.value),
                    ).classes("w-96")
                with ui.column().classes("gap-2") as describing:
                    kind = ui.toggle(
                        {TABLE: "A table", FOLDER: "A folder of files"}, value=TABLE
                    ).props("dense no-caps")
                    note(
                        "Say what the data are: the first dataset of a study, or a kind the "
                        "project has not had before. A table is copied into data/ as it is, with "
                        "no cleaning step, and its ID and date columns are chosen after the file. "
                        "A folder of files, such as scans or recordings, stays where it is; each "
                        "person's row counts their files."
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
                            with_input=True,
                            new_value_mode="add-unique",
                        ).classes("w-48")
                        reporter = ui.select(
                            config.vocab.reporters,
                            value=(config.vocab.reporters or [None])[0],
                            label="Reporter",
                            with_input=True,
                            new_value_mode="add-unique",
                        ).classes("w-48")
                    note("A modality or reporter not on the list can be typed in.")
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
            with ui.step(DATA_STEP):
                with ui.column().classes("gap-2 w-full") as table_box:
                    note(
                        "Choose the file as it came from the survey platform or the lab's "
                        "pipeline. labcatalog copies it into the project; the file you chose "
                        "stays where it is."
                    )
                    with ui.row().classes("items-center gap-3"):
                        ui.button("Choose the file", icon="upload_file", on_click=choose).props(
                            "flat"
                        ).classes("lc-quiet-btn")
                        chosen = ui.label().classes("lc-note")
                with ui.column().classes("gap-2 w-full") as folder_box:
                    note(
                        "Choose the folder, then say which files to count, with {id} where the "
                        "path holds the person's ID: * stands for any part of a name and **/ for "
                        "any folders in between."
                    )
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        folder_path = path_input(
                            "Folder", "", "Type or paste the path, or choose it"
                        )
                        folder_path.on("blur", scan_folder)
                        folder_path.on("keydown.enter", scan_folder)
                        ui.button(
                            "Choose the folder", icon="folder_open", on_click=choose_folder
                        ).props("flat").classes("lc-quiet-btn")
                    files = (
                        ui.input(
                            "Files",
                            placeholder="sub-{id}/ses-1/func/*_bold.nii.gz",
                            on_change=lambda: preview.refresh(),
                        )
                        .props("outlined dense")
                        .classes("w-full")
                    )
                    preview()
                with ui.column().classes("gap-2 w-full") as long_box:
                    note(
                        "The dataset it repeats reads one file that holds every wave, so this one "
                        "reads the same file and keeps the rows of its own wave."
                    )
                    rows_status = ui.label()
                folder_box.visible = long_box.visible = False
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
            with ui.step(CHECK_STEP):
                with ui.column().classes("gap-1") as dates_box:
                    with ui.row().classes("gap-3"):
                        starts = ui.input("Wave starts").classes("w-40")
                        ends = ui.input("Wave ends").classes("w-40")
                    for box in (starts, ends):
                        box.on("blur", dates_changed)
                        box.on("keydown.enter", dates_changed)
                    last_note = ui.label().classes("lc-note")
                dates_box.visible = False
                review()
                review_status = ui.label().classes("lc-bad-text")
                with ui.stepper_navigation():
                    ui.button("Add the dataset", icon="check", on_click=finish)
                    ui.button("Back", on_click=check_back).props("flat")
                    ui.button("Cancel", on_click=cancel).props("flat")
    # Closing the window halfway leaves no copied files behind.
    ui.context.client.on_disconnect(cleanup)
    dialog.open()
