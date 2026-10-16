from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from functools import partial

from nicegui import run, ui

from labcatalog import defaults
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import cited, note, panel, table
from labcatalog.gui.datasets import dataset_table
from labcatalog.issues import Issue
from labcatalog.metadata import changes, records, studies
from labcatalog.pipeline import CatalogResult

NO_REFERENCE = "(none)"


@dataclass
class StudiesView:
    study: str | None = None


def render(
    result: CatalogResult,
    view: StudiesView,
    on_saved: Callable[[], Awaitable[None]],
    on_dataset: Callable[[str], None],
) -> None:
    project = result.project
    config = project.config
    edited = {"now": False}

    def touched() -> None:
        edited["now"] = True
        for button in buttons:
            button.enable()

    def leave(then: Callable[[], None]) -> None:
        if not edited["now"]:
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
        edited["now"] = False
        page.refresh()

    def choose(study: str) -> None:
        if study != view.study:
            leave(partial(go, study))

    def create() -> None:
        with frame, ui.dialog() as dialog, ui.card():
            ui.label("New study")
            name = ui.input("ID", placeholder="for example pilot_study").classes("w-72")
            label = ui.input("Label", placeholder="for example Pilot Study").classes("w-72")

            async def make() -> None:
                study = (name.value or "").strip()
                try:
                    found = studies.new_study(project, study, (label.value or "").strip())
                    issues = await run.io_bound(changes.check, project, found)
                    if issues:
                        ui.notify(issues[0].message, type="warning", multi_line=True)
                        return
                    changes.write(project, found)
                except LabCatalogError as err:
                    ui.notify(str(err), type="negative", multi_line=True)
                    return
                dialog.close()
                view.study = study
                ui.notify(f"Added {study}")
                await on_saved()

            with ui.row():
                ui.button("Create", on_click=make)
                ui.button("Cancel", on_click=dialog.close).props("flat")
        dialog.open()

    @ui.refreshable
    def page() -> None:
        buttons.clear()
        names = list(config.studies)
        if view.study not in names:
            view.study = names[0] if names else None
        with ui.row().classes("w-full no-wrap items-start gap-6"):
            with ui.column().classes("w-64 shrink-0"), panel("Studies"):
                with ui.column().classes("w-full gap-0"):
                    for study in names:
                        item = ui.item(
                            config.studies[study].label or study, on_click=partial(choose, study)
                        ).props("dense clickable")
                        if study == view.study:
                            item.classes("lc-info font-medium")
                ui.button("New study", icon="add", on_click=lambda: leave(create)).props(
                    "flat dense no-caps"
                )
            with ui.column().classes("grow min-w-0 gap-4"):
                if view.study is None:
                    note("No studies yet; press New study to add one.")
                else:
                    detail(result, view.study, touched, buttons, on_saved, on_dataset, go)

    buttons: list[ui.button] = []
    with ui.element("div").classes("w-full") as frame:
        page()


def detail(
    result: CatalogResult,
    study: str,
    touched: Callable[[], None],
    buttons: list[ui.button],
    on_saved: Callable[[], Awaitable[None]],
    on_dataset: Callable[[str], None],
    go: Callable[[str | None], None],
) -> None:
    project = result.project
    found = project.config.studies[study]

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
        try:
            change = studies.edit_change(project, study, edited)
            issues = await run.io_bound(changes.check, project, [change])
            show(issues)
            if issues:
                ui.notify("Not saved: fix the problems listed below", type="warning")
                return
            changes.write(project, [change])
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        ui.notify(f"Saved {study}")
        await on_saved()

    def show(issues: list[Issue]) -> None:
        problems.clear()
        with problems:
            for issue in issues:
                ui.label(issue.message).classes("text-negative")

    with panel(found.label or study, study) as tools:
        with tools:
            buttons.append(ui.button("Discard", on_click=lambda: go(study)).props("flat no-caps"))
            buttons.append(ui.button("Save", icon="save", on_click=save))
        for button in buttons:
            button.disable()
        label = ui.input("Label", value=found.label or "", on_change=touched).classes("w-full")
        description = (
            ui.textarea("Description", value=found.description or "", on_change=touched)
            .props("autogrow")
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
        note(f"Reference is the key in {defaults.BIB_FILENAME} of how to cite the study's data.")
        problems = ui.column().classes("gap-1")

    today = date.today()
    holding = {}
    for dataset in project.config.datasets:
        if dataset.study == study:
            holding[dataset.wave] = holding.get(dataset.wave, 0) + 1
    wave_rows = [
        row
        | {
            "status": studies.wave_status(found.waves[row["wave"]], today),
            "datasets": holding.get(row["wave"], 0),
        }
        for row in studies.wave_rows(found)
    ]
    with panel("Waves", "A wave with no end date is still collecting.") as tools:
        waves = grid(
            [
                column("wave", "Wave"),
                column("start", "Start"),
                column("end", "End"),
                column("status", "Status", editable=False),
                column("datasets", "Datasets", editable=False),
            ],
            wave_rows,
            touched,
        )
        with tools:
            ui.button("Add wave", icon="add", on_click=partial(add_wave, waves, touched)).props(
                "flat dense no-caps"
            )
            delete_button(waves, touched)
        note("Dates are written as 2026-03-01. A wave that holds datasets cannot be removed.")

    with panel("Milestones", "Dates shown on the Overview timeline.") as tools:
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

    summaries = [
        s
        for s in result.summary.datasets
        if any(d.name == s.dataset and d.study == study for d in project.config.datasets)
    ]
    with panel("Datasets", "Click a row to open the dataset."):
        if not summaries:
            note(
                "No datasets yet. Add the first one to the Datasets table of labcatalog.yaml "
                "on the Edit page; later waves can then come in through Add a dataset."
            )
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
        .classes("w-full")
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
