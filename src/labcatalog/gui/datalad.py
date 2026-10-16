from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import run, ui

from labcatalog import defaults
from labcatalog.datalad.bridge import INSTALL, datalad_status, use_folder
from labcatalog.datalad.freeze import (
    RECORD_ONLY,
    Freeze,
    datalad_datasets,
    differences,
    list_freezes,
)
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences
from labcatalog.gui.common import col, heading, note, section, table
from labcatalog.paths import portable_path
from labcatalog.pipeline import CatalogResult, run_freeze


def get_button(
    label: str,
    function: Callable[..., None],
    args: list,
    on_done: Callable[[], Awaitable[None]],
) -> None:
    async def go() -> None:
        datalad = preferences.load().get(preferences.DATALAD)
        if not datalad:
            ui.notify("Set the path to datalad on the Settings page first", type="warning")
            return
        button.props("loading")
        try:
            await run.io_bound(function, *args, datalad)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        finally:
            button.props(remove="loading")
        await on_done()

    button = ui.button(label, icon="download", on_click=go).props("flat dense no-caps")


def datalad_section(on_datalad: Callable[[], Awaitable[None]]) -> None:
    section("DataLad")
    example = Path.home() / ".local" / "bin" / "datalad.exe"
    note(
        "When the data are in DataLad datasets, labcatalog records which version it read, "
        "freezes tag that version, and prepare steps can run through datalad run. Install "
        f"DataLad and git-annex yourself, for example with {INSTALL}, then give the path to "
        f"datalad, for example {example}."
    )
    path = (
        ui.input("datalad", value=preferences.load().get(preferences.DATALAD, ""))
        .props("outlined dense clearable")
        .classes("w-full max-w-2xl mt-2")
    )
    status = ui.label().classes("lc-note")

    async def save() -> None:
        value = (path.value or "").strip().strip('"')
        path.value = value
        preferences.save({preferences.DATALAD: value})
        if not value:
            status.set_text("No DataLad set.")
            return
        use_folder(value)
        status.set_text("Checking DataLad")
        try:
            found = await run.io_bound(datalad_status, value)
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        status.set_text(f"{found.datalad}, with git-annex {found.annex}.")
        await on_datalad()

    ui.button("Save and check", on_click=save).classes("mt-2")


def freeze_button(result: CatalogResult, on_frozen: Callable[[], Awaitable[None]]) -> None:
    root = result.project.root
    tagged = [
        "the project folder" if p == root else portable_path(p, root).as_posix()
        for p in datalad_datasets(result.project)
    ]

    def open_dialog() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
            ui.label("Freeze the data").classes("text-lg font-medium")
            note(
                "A freeze writes a record of every data file labcatalog reads (checksum, rows, "
                f"participants) to {defaults.FREEZES_DIR}, so you can say later which data a "
                "result used."
            )
            if tagged:
                note(
                    "The data are in DataLad, so the freeze also saves these datasets and tags "
                    f"them with its name, which lets you get this version back: {', '.join(tagged)}."
                )
            else:
                note(RECORD_ONLY)
            name = (
                ui.input("Name", placeholder="2026-06-submission")
                .props("outlined dense autofocus")
                .classes("w-full")
            )
            status = ui.label().classes("lc-note")

            async def go() -> None:
                datalad = preferences.load().get(preferences.DATALAD)
                status.set_text("Freezing")
                try:
                    path, record = await run.io_bound(
                        run_freeze, root, (name.value or "").strip(), datalad
                    )
                except LabCatalogError as err:
                    status.set_text(str(err))
                    return
                dialog.close()
                done = f"Froze {record.name} in {portable_path(path, root).as_posix()}"
                if record.tag:
                    done += f" and tagged {len(record.manifest.datalad)} DataLad dataset(s)"
                ui.notify(done)
                await on_frozen()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Freeze", on_click=go)
        dialog.open()

    with ui.row().classes("w-full justify-end"):
        ui.button("Freeze", icon="ac_unit", on_click=open_dialog).props("flat no-caps")


# Only a freeze with a DataLad tag has its data to open.
OPEN_CELL = r"""
<q-td :props="props">
  <q-btn v-if="props.row.tagged" flat dense no-caps color="primary" label="Open"
         @click="$parent.$emit('open_freeze', props.row)" />
</q-td>
"""


def freezes_table(root: Path, on_open: Callable[[str], Awaitable[None]] | None) -> None:
    found = list_freezes(root)
    if not found:
        return
    heading("Freezes")
    columns = [
        col("frozen", "Frozen"),
        col("name", "Name"),
        col("tag", "DataLad tag"),
        col("files", "Data files", numeric=True),
    ]
    if on_open:
        columns.append(col("open", "", sortable=False))
    rows = [
        {
            "frozen": f.frozen_at.strftime("%Y-%m-%d %H:%M"),
            "name": f.name,
            "tag": f.tag or "none, record only",
            "files": len(f.manifest.files),
            "tagged": f.tag is not None,
        }
        for f in found
    ]
    shown = table(columns, rows).classes(remove="w-full")
    if on_open:
        shown.add_slot("body-cell-open", OPEN_CELL)
        shown.on("open_freeze", lambda e: on_open(e.args["name"]))


def frozen_text(record: Freeze, result: CatalogResult | None) -> str:
    text = f"Frozen version {record.name}, a copy: edits here do not change the project"
    if result is None or result.manifest is None:
        return text
    changed = differences(record, result.manifest)
    if changed:
        return f"{text}. Differs from the freeze record: {', '.join(changed)}"
    return f"{text}. All {len(record.manifest.files)} data files match the freeze record"
