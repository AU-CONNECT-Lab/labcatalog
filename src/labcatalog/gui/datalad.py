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
    freeze_roots,
    list_freezes,
    push_targets,
)
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences
from labcatalog.gui.common import (
    col,
    command,
    computed,
    note,
    panel,
    path_input,
    show_status,
    table,
)
from labcatalog.paths import portable_path
from labcatalog.pipeline import CatalogResult, run_freeze, run_push_freeze


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
    example = Path.home() / ".local" / "bin" / "datalad.exe"
    with panel("DataLad", "Versions of the data, freezes and datalad run"):
        note(
            "When the data are in DataLad datasets, labcatalog records which version it read, "
            "freezes tag that version, and prepare steps can run through datalad run. Install "
            "DataLad and git-annex yourself, for example by typing these in a terminal:"
        )
        for line in INSTALL:
            command(line)
        with ui.row().classes("w-full items-start no-wrap gap-2 mt-1"):
            path = path_input(
                "datalad", preferences.load().get(preferences.DATALAD, ""), f"For example {example}"
            )
            button = ui.button("Save and check")
        status = ui.label()
        status.visible = False

    async def save() -> None:
        value = (path.value or "").strip().strip('"')
        path.value = value
        preferences.save({preferences.DATALAD: value})
        if not value:
            show_status(status, "No DataLad set.", "warn")
            return
        use_folder(value)
        show_status(status, "Checking DataLad", "info")
        try:
            found = await computed(datalad_status, value)
        except LabCatalogError as err:
            show_status(status, str(err), "bad")
            return
        show_status(status, f"{found.datalad}, with git-annex {found.annex}.", "ok")
        await on_datalad()

    button.on_click(save)
    path.on("keydown.enter", save)


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
            push = None
            if tagged:
                note(
                    "The data are in DataLad, so the freeze also saves these datasets and tags "
                    f"them with its name, which lets you get this version back: {', '.join(tagged)}."
                )
                targets = push_targets(freeze_roots(result.project))
                siblings = sorted({t for t in targets.values() if t})
                if siblings:
                    push = ui.checkbox(
                        f"Then push the tag and the data to {', '.join(siblings)}", value=True
                    )
                unclear = [portable_path(r, root).as_posix() for r, t in targets.items() if not t]
                if unclear:
                    note(
                        f"{', '.join(unclear)} has no single sibling to push to; push it "
                        "yourself after freezing."
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
                    path, record = await computed(
                        run_freeze, root, (name.value or "").strip(), datalad
                    )
                except LabCatalogError as err:
                    status.set_text(str(err))
                    return
                done = f"Froze {record.name} in {portable_path(path, root).as_posix()}"
                if record.tag:
                    done += f" and tagged {len(record.manifest.datalad)} DataLad dataset(s)"
                if push is not None and push.value:
                    status.set_text("Pushing")
                    try:
                        pushed = await computed(run_push_freeze, root, record.name, datalad)
                        done += f", pushed {len(pushed)}"
                    except LabCatalogError as err:
                        # The freeze stands; only the push is left to do.
                        done += f", but the push failed: {err}"
                dialog.close()
                ui.notify(done, multi_line=True)
                await on_frozen()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Freeze", on_click=go)
        dialog.open()

    ui.button("Freeze", icon="ac_unit", on_click=open_dialog).props("flat no-caps").classes(
        "lc-quiet-btn"
    )


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
    with panel("Freezes", "Records of the data a result used"):
        shown = table(columns, rows)
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
