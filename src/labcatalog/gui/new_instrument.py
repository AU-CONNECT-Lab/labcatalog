import difflib
from collections.abc import Awaitable, Callable

from nicegui import ui

from labcatalog.charts import views
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, note
from labcatalog.gui.edit import cell, grid_options
from labcatalog.gui.files import PDF_FILES, choose_path
from labcatalog.metadata import changes, new_instrument, records
from labcatalog.metadata.completeness import QUESTIONNAIRE
from labcatalog.paths import portable_path, posix_str
from labcatalog.pipeline import CatalogResult
from labcatalog.project import references_root

TITLES = {
    "about": "About",
    "options": "Answer options",
    "items": "Items",
    "scores": "Scores",
    "given": "Where it is given",
    "check": "Check and save",
}


class TableEditor:
    # One of the Edit files tables, with rows added and ticked rows deleted.
    def __init__(self, table: records.Table, rows: list[dict]) -> None:
        self.table = table
        self.grid = ui.aggrid(grid_options(table, rows)).classes("w-full").style("height: 40vh")
        # A step not shown yet has no grid in the browser, and nothing edited in it.
        self.shown = False

    def column(self, key: str) -> dict:
        return next(d for d in self.grid.options["columnDefs"] if d["field"] == key)

    async def rows(self) -> list[dict]:
        if not self.shown:
            return self.grid.options["rowData"]
        return await self.grid.get_client_data(method="filtered_sorted")

    def blank(self) -> dict:
        return {c.key: cell(records.shown(None, c), c) for c in self.table.columns}

    async def add(self, rows: list[dict]) -> None:
        # Rows come as the grid shows them, so only missing cells take the column's default.
        shown = [
            {
                c.key: cell(r[c.key] if c.key in r else records.shown(None, c), c)
                for c in self.table.columns
            }
            for r in rows
        ]
        self.set([*await self.rows(), *shown])

    async def delete_ticked(self) -> None:
        ticked = await self.grid.get_selected_rows()
        if not ticked:
            ui.notify("Tick the rows to delete first")
            return
        self.set([r for r in await self.rows() if r not in ticked])

    def set(self, rows: list[dict]) -> None:
        self.grid.options["rowData"] = rows
        self.grid.update()


def open_wizard(
    result: CatalogResult,
    on_done: Callable[[str], Awaitable[None]],
    instrument_id: str | None = None,
) -> None:
    project = result.project
    completing = instrument_id is not None
    try:
        draft = (
            new_instrument.existing(project, instrument_id)
            if completing
            else new_instrument.Draft("")
        )
    except LabCatalogError as err:
        ui.notify(
            f"{err}. Use the Codebook step of the Set up page for this instrument.", type="negative"
        )
        return
    first = new_instrument.first_gap(project, instrument_id) if completing else "about"
    tables = records.INSTRUMENT_TABLES
    state: dict = {"changes": [], "step": TITLES[first]}
    modalities = list(
        dict.fromkeys(
            [QUESTIONNAIRE, *project.config.vocab.modalities]
            + [i.modality for i in project.instruments.values()]
        )
    )
    with_sets = {
        i: s.abbreviation or s.name for i, s in project.instruments.items() if s.response_sets
    }
    given = set(new_instrument.given_in(project, instrument_id)) if completing else set()

    def collect_about() -> None:
        draft.id = (id_input.value or "").strip()
        draft.about = {
            "name": name.value or "",
            "abbreviation": abbreviation.value or "",
            "modality": modality.value or QUESTIONNAIRE,
            "construct_name": construct.value or "",
            "description": description.value or "",
            "license": license_input.value or "",
        }
        draft.demographics = demographics.value
        draft.references = list(reference.value or [])
        draft.pdfs = {k: v for k, v in draft.pdfs.items() if k in draft.references and v}

    async def choose_pdf(key: str) -> None:
        root = references_root(project.config, project.root)
        found = await choose_path(file_types=(PDF_FILES,), start=root)
        if found:
            draft.pdfs[key] = posix_str(portable_path(found, root))
            pdf_rows.refresh()

    def set_pdf(key: str, value: str) -> None:
        draft.pdfs[key] = (value or "").strip()

    @ui.refreshable
    def pdf_rows() -> None:
        for key in reference.value or []:
            with ui.row().classes("items-center gap-3 w-full no-wrap"):
                ui.input(
                    f"PDF of {key} (in the references folder)",
                    value=draft.pdfs.get(key, ""),
                    on_change=lambda e, k=key: set_pdf(k, e.value),
                ).classes("grow")
                ui.button("Choose", on_click=lambda k=key: choose_pdf(k)).props("flat")

    def about_next() -> None:
        collect_about()
        try:
            new_instrument.check_about(project, draft)
        except LabCatalogError as err:
            about_status.set_text(str(err))
            return
        about_status.set_text("")
        stepper.next()

    async def copy_sets() -> None:
        if copy_from.value:
            await options.add(new_instrument.copy_options(project, copy_from.value))

    async def sync_options() -> None:
        draft.options = await options.rows()
        sets = list(dict.fromkeys(str(r["id"]) for r in draft.options if r.get("id")))
        if draft.default_set not in sets:
            draft.default_set = sets[0] if sets else ""
        default_set.set_options(["", *sets], value=draft.default_set)
        items.column("response_set").update(
            cellEditor="agSelectCellEditor", cellEditorParams={"values": ["", *sets]}
        )
        items.grid.update()

    async def paste_items() -> None:
        draft.items = await items.rows()
        collect_about()
        await items.add(new_instrument.items_from_lines(draft, pasted.value or ""))
        pasted.set_value("")

    async def sync_items() -> None:
        draft.items = await items.rows()
        draft.default_set = default_set.value or ""
        ids = [str(r["id"]) for r in draft.items]
        scores.column("items").update(headerName=f"Items ({', '.join(ids)})")
        scores.grid.update()

    def show(step: str) -> None:
        editors = {TITLES["options"]: options, TITLES["items"]: items, TITLES["scores"]: scores}
        if step in editors:
            editors[step].shown = True

    async def left_step(e) -> None:
        # The header also moves between steps, so leaving a step does what its Next did.
        left, state["step"] = state["step"], e.value
        show(e.value)
        if left == TITLES["about"]:
            collect_about()
        elif left == TITLES["options"]:
            await sync_options()
        elif left == TITLES["items"]:
            await sync_items()

    async def add_total() -> None:
        await scores.add([new_instrument.suggest_total(draft)])

    async def collect() -> None:
        # Every step's tables, since completing an instrument may start halfway through.
        collect_about()
        draft.options = await options.rows()
        draft.items = await items.rows()
        draft.default_set = default_set.value or ""
        draft.scores = await scores.rows()

    async def find_columns() -> None:
        await collect()
        rows = []
        ids = [str(r["id"]) for r in draft.items if r.get("id")]
        for dataset in chosen.value or []:
            try:
                guessed = await computed(new_instrument.guess_columns, project, dataset, ids)
                free = await computed(new_instrument.free_columns_of, project, dataset)
            except LabCatalogError as err:
                given_status.set_text(str(err))
                return
            rows += [
                {
                    "dataset": dataset,
                    "item": i,
                    "column": guessed.get(i, ""),
                    "choices": ["", *free],
                }
                for i in ids
            ]
        columns.options["rowData"] = rows
        columns.update()

    async def given_next() -> None:
        await collect()
        try:
            new_instrument.check_about(project, draft)
        except LabCatalogError as err:
            given_status.set_text(f"About: {err}")
            return
        draft.given = {}
        for row in await columns.get_client_data():
            draft.given.setdefault(row["dataset"], {})[row["item"]] = row.get("column") or ""
        try:
            found = new_instrument.changes(project, draft)
        except LabCatalogError as err:
            given_status.set_text(str(err))
            return
        issues = changes.check(project, found)
        if issues:
            given_status.set_text("; ".join(str(i) for i in issues))
            return
        given_status.set_text("")
        state["changes"] = found
        review.refresh()
        stepper.next()

    @ui.refreshable
    def review() -> None:
        if not state["changes"]:
            return
        note("These files change; each line with + is new and each line with - goes.")
        for change in state["changes"]:
            before = change.opened.text if change.opened else ""
            lines = difflib.unified_diff(
                before.splitlines(), change.text.splitlines(), lineterm="", n=0
            )
            shown = [line for line in lines if line[:1] in "+-" and line[:3] not in ("+++", "---")]
            if not shown:
                continue
            ui.label(change.path + ("" if change.opened else " (new)")).classes("font-medium")
            ui.code("\n".join(shown), language="diff").classes("w-full lc-wrap")

    async def finish() -> None:
        try:
            changes.write(project, state["changes"])
        except LabCatalogError as err:
            review_status.set_text(str(err))
            return
        dialog.close()
        await on_done(draft.id)

    def navigation(on_next: Callable, back: bool = True) -> None:
        with ui.stepper_navigation():
            ui.button("Next", on_click=on_next)
            if back:
                ui.button("Back", on_click=stepper.previous).props("flat")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    title = (
        f"Complete {draft.about.get('name', instrument_id)}" if completing else "Add an instrument"
    )
    with ui.dialog().props("persistent") as dialog, ui.card().classes("w-[76rem] max-w-full"):
        ui.label(title).classes("text-lg font-medium")
        with (
            ui.stepper(value=TITLES[first], on_value_change=left_step)
            .props("flat animated header-nav")
            .classes("w-full") as stepper
        ):
            with ui.step(TITLES["about"]):
                with ui.row().classes("gap-3"):
                    id_input = ui.input("ID", value=draft.id).classes("w-56")
                    id_input.set_enabled(not completing)
                    name = ui.input("Name", value=draft.about.get("name", "")).classes("w-96")
                    abbreviation = ui.input(
                        "Abbreviation", value=draft.about.get("abbreviation", "")
                    ).classes("w-32")
                with ui.row().classes("gap-3 items-center"):
                    modality = ui.select(
                        modalities,
                        value=draft.about.get("modality", QUESTIONNAIRE),
                        label="Modality",
                        new_value_mode="add-unique",
                    ).classes("w-48")
                    demographics = ui.checkbox("Demographics form", value=draft.demographics)
                    construct = ui.input(
                        "Construct", value=draft.about.get("construct_name", "")
                    ).classes("w-96")
                description = (
                    ui.textarea("Description", value=draft.about.get("description", ""))
                    .props("autogrow")
                    .classes("w-full")
                )
                with ui.row().classes("gap-3 w-full"):
                    reference = (
                        ui.select(
                            sorted(project.bibliography),
                            value=draft.references,
                            label="References (keys in references.bib)",
                            multiple=True,
                            on_change=lambda: pdf_rows.refresh(),
                        )
                        .props("use-chips")
                        .classes("w-96")
                    )
                    license_input = ui.input(
                        "License", value=draft.about.get("license", "")
                    ).classes("grow")
                pdf_rows()
                note(
                    "The ID names the file and goes before every item's ID. A reference that is "
                    "not in references.bib yet is added there by whoever looks after the settings."
                )
                about_status = ui.label().classes("lc-bad-text")
                navigation(about_next, back=False)
            with ui.step(TITLES["options"]):
                note(
                    "Each row is one answer: the set it belongs to, the value in the data and its "
                    "label. Copy the sets of an instrument with the same answers, or type them."
                )
                with ui.row().classes("items-center gap-3"):
                    copy_from = ui.select(with_sets, label="Copy the sets of").classes("w-64")
                    ui.button("Copy", on_click=copy_sets).props("flat no-caps")
                    ui.space()
                    ui.button("Add row", on_click=lambda: options.add([options.blank()])).props(
                        "flat no-caps"
                    )
                    ui.button("Delete ticked rows", on_click=lambda: options.delete_ticked()).props(
                        "flat no-caps"
                    )
                options = TableEditor(tables["response_sets"], draft.options)
                navigation(stepper.next)
            with ui.step(TITLES["items"]):
                with ui.row().classes("w-full items-end gap-3 no-wrap"):
                    pasted = (
                        ui.textarea(
                            "Paste the items, one per line; end a line with (R) for a "
                            "reverse-keyed item"
                        )
                        .props("autogrow")
                        .classes("grow")
                    )
                    ui.button("Add these items", on_click=paste_items).props("no-caps")
                with ui.row().classes("items-center gap-3 w-full"):
                    default_set = ui.select(
                        ["", draft.default_set] if draft.default_set else [""],
                        value=draft.default_set,
                        label="Response set of items that name none",
                    ).classes("w-72")
                    ui.space()
                    ui.button("Add row", on_click=lambda: items.add([items.blank()])).props(
                        "flat no-caps"
                    )
                    ui.button("Delete ticked rows", on_click=lambda: items.delete_ticked()).props(
                        "flat no-caps"
                    )
                items = TableEditor(tables["items"], draft.items)
                navigation(stepper.next)
            with ui.step(TITLES["scores"]):
                note(
                    "Each score adds up (sum) or averages (mean) its items, listed by ID with "
                    "commas. Missing says what to do when an item is unanswered: complete needs "
                    "every item, prorate fills in the person's mean when at least Min answered "
                    "items are answered."
                )
                with ui.row().classes("items-center gap-3 w-full"):
                    ui.button("Add a total score", on_click=add_total).props("flat no-caps")
                    ui.space()
                    ui.button("Add row", on_click=lambda: scores.add([scores.blank()])).props(
                        "flat no-caps"
                    )
                    ui.button("Delete ticked rows", on_click=lambda: scores.delete_ticked()).props(
                        "flat no-caps"
                    )
                scores = TableEditor(tables["scores"], draft.scores)
                navigation(stepper.next)
            with ui.step(TITLES["given"]):
                if given:
                    note(f"Already given in {', '.join(sorted(given))}.")
                note(
                    "Choose the datasets that have this instrument's columns, then Find the "
                    "columns. Check each guess; leave Column empty for an item a dataset lacks."
                )
                with ui.row().classes("items-center gap-3"):
                    chosen = (
                        ui.select(
                            {
                                d.name: views.dataset_label(result, d.name)
                                for d in project.config.datasets
                                if d.name not in given
                            },
                            value=[],
                            label="Datasets",
                            multiple=True,
                        )
                        .props("use-chips")
                        .classes("w-[36rem]")
                    )
                    ui.button("Find the columns", on_click=find_columns).props("no-caps")
                columns = (
                    ui.aggrid(
                        {
                            "columnDefs": [
                                {"field": "dataset", "headerName": "Dataset", "flex": 1},
                                {"field": "item", "headerName": "Item", "flex": 1},
                                {
                                    "field": "column",
                                    "headerName": "Column",
                                    "editable": True,
                                    "cellEditor": "agSelectCellEditor",
                                    ":cellEditorParams": "p => ({values: p.data.choices})",
                                    "flex": 2,
                                },
                            ],
                            "rowData": [],
                            "stopEditingWhenCellsLoseFocus": True,
                        }
                    )
                    .classes("w-full")
                    .style("height: 40vh")
                )
                given_status = ui.label().classes("lc-bad-text")
                navigation(given_next)
            # Check and save shows what Next on the step before it worked out.
            with ui.step(TITLES["check"]) as check_step:
                check_step.props["header-nav"] = False
                review()
                review_status = ui.label().classes("lc-bad-text")
                with ui.stepper_navigation():
                    ui.button("Save", icon="check", on_click=finish)
                    ui.button("Back", on_click=stepper.previous).props("flat")
                    ui.button("Cancel", on_click=dialog.close).props("flat")
    show(TITLES[first])
    dialog.open()
