from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from functools import partial

from nicegui import ui

from labcatalog import defaults
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import charts, new_dataset
from labcatalog.gui.common import as_text, cited, computed, note, panel, table
from labcatalog.gui.datasets import dataset_table
from labcatalog.issues import Issue
from labcatalog.metadata import changes, records, studies
from labcatalog.pipeline import CatalogResult

NO_REFERENCE = "(none)"
TABS = {"study": "Study", "text": "Procedure", "datasets": "Datasets"}


@dataclass
class StudiesView:
    study: str | None = None
    tab: str = "study"
    # Unsaved changes on the page, which another page's choice of study must not drop unasked.
    edited: bool = False


def render(
    result: CatalogResult,
    view: StudiesView,
    on_saved: Callable[..., Awaitable[None]],
    on_dataset: Callable[[str], None],
    on_added: Callable[[str], Awaitable[None]],
) -> None:
    project = result.project
    config = project.config
    view.edited = False

    def touched() -> None:
        view.edited = True
        for button in buttons:
            button.enable()

    def leave(then: Callable[[], None]) -> None:
        if not view.edited:
            then()
            return
        with frame, ui.dialog() as dialog, ui.card():
            ui.label(f"Discard your changes to {view.study}?")
            with ui.row():
                ui.button("Discard", on_click=lambda: (dialog.close(), then()))
                ui.button("Keep editing", on_click=dialog.close).props("flat")
        dialog.open()

    def go(study: str | None) -> None:
        view.study = study
        view.edited = False
        page.refresh()

    def choose(study: str) -> None:
        if study != view.study:
            leave(partial(go, study))

    async def made(study: str) -> None:
        view.study = study
        await on_saved()

    async def apply(found: list, old: str, new: str | None) -> bool:
        if not await write(project, found):
            return False
        view.study = new
        await on_saved(old, new)
        return True

    def rename() -> None:
        old = view.study
        with frame, ui.dialog() as dialog, ui.card().classes("w-[32rem]"):
            ui.label(f"Rename {old}")
            name = ui.input("New ID", value=old).classes("w-72")
            note(
                f"The ID changes under studies in {defaults.CONFIG_FILENAME}, in each of the "
                "study's datasets and in its study file, which takes the new name. Warnings you "
                "marked as fine that name the old ID show again."
            )

            async def make() -> None:
                new = (name.value or "").strip()
                try:
                    found = studies.rename_study(project, old, new)
                except LabCatalogError as err:
                    ui.notify(str(err), type="negative")
                    return
                if await apply(found, old, new):
                    dialog.close()
                    ui.notify(f"Renamed {old} to {new}")

            with ui.row():
                ui.button("Rename", on_click=make)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    def delete() -> None:
        study = view.study
        try:
            found = studies.delete_study(project, study)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative")
            return
        mine = [d for d in config.datasets if d.study == study]
        removed = [c.path for c in found if c.removed]
        with frame, ui.dialog() as dialog, ui.card().classes("w-[36rem]"):
            ui.label(f"Delete {config.studies[study].label or study}?").classes("font-medium")
            ui.label(f"Removes the study from {defaults.CONFIG_FILENAME}, and with it:")
            with ui.column().classes("gap-0 pl-4"):
                if mine:
                    names = ", ".join(d.name for d in mine)
                    ui.label(f"{len(mine)} datasets: {names}")
                for path in removed:
                    ui.label(path)
            if mine:
                note(
                    "The data files stay where they are, and so do any prepare steps that make "
                    "them. To undo, restore the files from git or DataLad."
                )
            typed = ui.input(f"Type {study} to confirm").classes("w-72")

            async def remove() -> None:
                if await apply(found, study, None):
                    dialog.close()
                    ui.notify(f"Deleted {study}")

            with ui.row():
                button = ui.button("Delete", icon="delete", color="negative", on_click=remove)
                ui.button("Cancel", on_click=dialog.close).props("flat")
            button.disable()
            typed.on_value_change(lambda e: button.set_enabled(e.value == study))
        dialog.open()

    @ui.refreshable
    def page() -> None:
        buttons.clear()
        names = list(config.studies)
        if view.study not in names:
            view.study = names[0] if names else None
        with ui.row().classes("w-full no-wrap items-start gap-6"):
            with ui.column().classes("w-64 shrink-0 lc-side"), panel("Studies"):
                with ui.column().classes("w-full gap-0"):
                    for study in names:
                        item = (
                            ui.item(
                                config.studies[study].label or study,
                                on_click=partial(choose, study),
                            )
                            .props("dense clickable")
                            .classes("lc-pick")
                        )
                        if study == view.study:
                            item.classes("lc-info font-medium")
                ui.button(
                    "New study",
                    icon="add",
                    on_click=lambda: leave(partial(new_study, project, made)),
                ).props("flat dense no-caps")
            with ui.column().classes("grow min-w-0 gap-4"):
                if view.study is None:
                    note("No studies yet; press New study to add one.")
                    return
                actions = Actions(
                    touched, go, lambda: leave(rename), lambda: leave(delete), on_saved, on_dataset
                )
                detail(result, view, buttons, actions, on_added)

    buttons: list[ui.button] = []
    with ui.element("div").classes("w-full") as frame:
        page()


async def write(project, found: list) -> bool:
    # Checks the project with the changes in place before writing them.
    try:
        issues = await computed(changes.check, project, found)
        if issues:
            ui.notify(issues[0].message, type="warning", multi_line=True)
            return False
        changes.write(project, found)
    except LabCatalogError as err:
        ui.notify(str(err), type="negative", multi_line=True)
        return False
    return True


def new_study(project, on_made: Callable[[str], Awaitable[None]]) -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("New study")
        name = ui.input("ID", placeholder="for example pilot_study").classes("w-72")
        label = ui.input("Label", placeholder="for example Pilot Study").classes("w-72")

        async def make() -> None:
            study = (name.value or "").strip()
            try:
                found = studies.new_study(project, study, (label.value or "").strip())
            except LabCatalogError as err:
                ui.notify(str(err), type="negative")
                return
            if await write(project, found):
                dialog.close()
                ui.notify(f"Added {study}")
                await on_made(study)

        with ui.row():
            ui.button("Create", on_click=make)
            ui.button("Cancel", on_click=dialog.close).props("flat")
    dialog.open()


@dataclass
class Actions:
    touched: Callable[[], None]
    go: Callable[[str | None], None]
    rename: Callable[[], None]
    delete: Callable[[], None]
    on_saved: Callable[..., Awaitable[None]]
    on_dataset: Callable[[str], None]


def detail(
    result: CatalogResult,
    view: StudiesView,
    buttons: list[ui.button],
    actions: Actions,
    on_added: Callable[[str], Awaitable[None]],
) -> None:
    project = result.project
    study = view.study
    found = project.config.studies[study]
    touched = actions.touched

    async def save() -> None:
        edited = studies.Edited(
            {
                "label": label.value,
                "description": description.value,
                "reference": "" if reference.value == NO_REFERENCE else reference.value,
            },
            await waves.get_client_data(method="filtered_sorted"),
            await milestones.get_client_data(method="filtered_sorted"),
        )
        texts = {modality: box.value or "" for modality, box in boxes.items()}
        try:
            pending = [
                studies.edit_change(project, study, edited),
                studies.text_change(project, study, texts),
            ]
            pending = [c for c in pending if c and (c.opened is None or c.text != c.opened.text)]
            issues = await computed(changes.check, project, pending)
            show(issues)
            if issues:
                ui.notify("Not saved: fix the problems listed above", type="warning")
                return
            changes.write(project, pending)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        ui.notify(f"Saved {study}")
        await actions.on_saved()

    def show(issues: list[Issue]) -> None:
        problems.clear()
        with problems:
            for issue in issues:
                ui.label(issue.message).classes("text-negative")

    def switch(tab: str) -> None:
        view.tab = tab
        for name, shown in parts.items():
            shown.visible = name == tab

    with panel(found.label or study, study) as tools:
        with tools:
            ui.button("Rename", icon="edit", on_click=actions.rename).props("flat dense no-caps")
            ui.button("Delete", icon="delete", on_click=actions.delete).props("flat dense no-caps")
            buttons.append(
                ui.button("Discard", on_click=lambda: actions.go(study)).props("flat no-caps")
            )
            buttons.append(ui.button("Save", icon="save", on_click=save))
        for button in buttons:
            button.disable()
        # Hidden rather than unmounted, so Save can read the tables on every tab.
        ui.toggle(TABS, value=view.tab, on_change=lambda e: switch(e.value)).props("dense no-caps")
        problems = ui.column().classes("gap-1")

    parts = {name: ui.column().classes("w-full gap-4") for name in TABS}
    with parts["study"]:
        with panel("About"):
            label = ui.input("Label", value=found.label or "", on_change=touched).classes("w-full")
            description = (
                ui.textarea("Description", value=found.description or "", on_change=touched)
                .classes("lc-grow")
                .classes("w-full")
            )
            keys = sorted({*project.bibliography, *([found.reference] if found.reference else [])})
            with ui.row().classes("w-full items-center gap-4"):
                reference = ui.select(
                    [NO_REFERENCE, *keys],
                    value=found.reference or NO_REFERENCE,
                    label="Reference",
                    with_input=True,
                    on_change=touched,
                ).classes("w-72")
                if found.reference:
                    with ui.row().classes("items-baseline gap-2"):
                        ui.label("How to cite").classes("lc-note")
                        cited(project.bibliography, found.reference)
            note(
                f"Reference is the key in {defaults.BIB_FILENAME} of how to cite the study's data."
            )
            fields = [
                f
                for f in project.config.custom_fields
                if f.applies_to == "study" and f.name in found.custom
            ]
            for f in fields:
                ui.label(f"{f.label or f.name.capitalize()}: {as_text(found.custom[f.name])}")
            if fields:
                note(f"Custom fields are set under studies in {defaults.CONFIG_FILENAME}.")
        waves = waves_panel(project, study, touched)
        milestones = milestones_panel(found, touched)
        charts.collection_pace(result, study)
    with parts["text"]:
        boxes = text_panels(result, study, touched)
    with parts["datasets"]:
        datasets_panel(result, study, actions.on_dataset, on_added)
    switch(view.tab)


def waves_panel(project, study: str, touched: Callable[[], None]) -> ui.aggrid:
    found = project.config.studies[study]
    today = date.today()
    holding: dict[str, int] = {}
    for dataset in project.config.datasets:
        if dataset.study == study:
            holding[dataset.wave] = holding.get(dataset.wave, 0) + 1
    rows = [
        row
        | {
            "status": studies.wave_status(found.waves[row["wave"]], today),
            "datasets": holding.get(row["wave"], 0),
        }
        for row in studies.wave_rows(found)
    ]
    with panel("Waves", help_text="A wave with no end date is still collecting.") as tools:
        waves = grid(
            [
                column("wave", "Wave"),
                column("start", "Start"),
                column("end", "End"),
                column("status", "Status", editable=False),
                column("datasets", "Datasets", editable=False),
            ],
            rows,
            touched,
        )
        with tools:
            ui.button("Add wave", icon="add", on_click=partial(add_wave, waves, touched)).props(
                "flat dense no-caps"
            )
            delete_button(waves, touched)
        note("Dates are written as 2026-03-01. A wave that holds datasets cannot be removed.")
    return waves


def milestones_panel(found, touched: Callable[[], None]) -> ui.aggrid:
    with panel("Milestones", help_text="Dates shown on the Overview timeline.") as tools:
        milestones = grid(
            [column("name", "Name", flex=3), column("date", "Date")],
            studies.milestone_rows(found),
            touched,
        )
        with tools:
            ui.button(
                "Add milestone",
                icon="add",
                on_click=partial(add_row, milestones, {"name": "", "date": ""}, touched),
            ).props("flat dense no-caps")
            delete_button(milestones, touched)
    return milestones


def text_panels(
    result: CatalogResult, study: str, touched: Callable[[], None]
) -> dict[str, ui.textarea]:
    project = result.project
    vocab = project.config.vocab
    content = next((c for c in project.studies.values() if c.study == study), None)
    written = content.methods if content else {}
    used = {d.modality for d in project.config.datasets if d.study == study} | set(written)
    modalities = [m for m in vocab.modalities if m in used] + sorted(used - set(vocab.modalities))
    boxes = {}
    with panel(
        "Procedure",
        help_text="How each modality's data were collected and processed, for the Methods page.",
    ):
        if not modalities:
            note("The study has no datasets yet; each modality it uses gets a box here.")
        names = {d.name for d in project.config.datasets if d.study == study}
        for modality in modalities:
            boxes[modality] = (
                ui.textarea(
                    f"{modality} (dataset)"
                    if modality in names
                    else vocab.modality_label(modality),
                    value=written.get(modality, "").strip(),
                    on_change=touched,
                )
                .classes("lc-grow")
                .classes("w-full")
            )
        note("Leave a blank line between paragraphs.")
    return boxes


def datasets_panel(
    result: CatalogResult,
    study: str,
    on_dataset: Callable[[str], None],
    on_added: Callable[[str], Awaitable[None]],
) -> None:
    config = result.project.config
    mine = {d.name for d in config.datasets if d.study == study}
    summaries = [s for s in result.summary.datasets if s.dataset in mine]
    with panel("Datasets", help_text="Click a row to open the dataset.") as tools:
        with tools:
            ui.button(
                "Add a dataset" if summaries else "Add the first dataset",
                icon="add",
                # A study with datasets usually repeats one; a new one starts from nothing.
                on_click=lambda: new_dataset.open_wizard(
                    result, on_added, None if summaries else study
                ),
            ).props("flat dense no-caps")
        if not summaries:
            note("No datasets yet.")
        else:
            shown = table(*dataset_table(result, summaries)).classes("cursor-pointer")
            shown.on("rowClick", lambda e: on_dataset(e.args[1]["name"]))


def column(field: str, header: str, editable: bool = True, flex: int = 1) -> dict:
    return {
        "field": field,
        "headerName": header,
        "editable": editable,
        "flex": flex,
        "cellDataType": "text",
    }


def grid(columns: list[dict], rows: list[dict], touched: Callable[[], None]) -> ui.aggrid:
    return (
        ui.aggrid(
            {
                "columnDefs": columns,
                "rowData": rows,
                "rowSelection": {"mode": "multiRow"},
                "stopEditingWhenCellsLoseFocus": True,
                "domLayout": "autoHeight",
                "defaultColDef": {"resizable": True},
            }
        )
        .classes("w-full lc-fit")
        .style("height: auto")
        .on("cellValueChanged", touched)
    )


async def add_wave(waves: ui.aggrid, touched: Callable[[], None]) -> None:
    rows = await waves.get_client_data(method="filtered_sorted")
    numbers = [int(r["wave"]) for r in rows if str(r["wave"]).isdigit()]
    wave = str(max(numbers) + 1) if numbers else "1"
    blank = {"wave": wave, "start": "", "end": "", "status": "", "datasets": 0}
    await add_row(waves, blank, touched)


async def add_row(shown: ui.aggrid, blank: dict, touched: Callable[[], None]) -> None:
    rows = await shown.get_client_data(method="filtered_sorted")
    set_rows(shown, [*rows, {records.ORIGIN: None} | blank], touched)


def delete_button(shown: ui.aggrid, touched: Callable[[], None]) -> None:
    async def delete() -> None:
        selected = await shown.get_selected_rows()
        if not selected:
            ui.notify("Tick the rows to delete first")
            return
        rows = await shown.get_client_data(method="filtered_sorted")
        set_rows(shown, [r for r in rows if r not in selected], touched)

    ui.button("Delete ticked", icon="delete", on_click=delete).props("flat dense no-caps")


def set_rows(shown: ui.aggrid, rows: list[dict], touched: Callable[[], None]) -> None:
    shown.options["rowData"] = rows
    shown.update()
    touched()
