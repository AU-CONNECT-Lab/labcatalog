import sys
from collections.abc import Awaitable, Callable
from functools import partial
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
from labcatalog.datalad.sync import (
    DatasetState,
    dataset_states,
    project_datasets,
    size_text,
    state_text,
)
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common, preferences
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
from labcatalog.gui.files import FOLDER, allowed, choose_path
from labcatalog.gui.look import look
from labcatalog.paths import portable_path
from labcatalog.pipeline import (
    CatalogResult,
    run_clone,
    run_data_push,
    run_data_save,
    run_data_update,
    run_drop_dataset,
    run_freeze,
    run_get_dataset,
    run_history,
    run_push_freeze,
    run_rerun,
)


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
    example = (
        Path.home() / ".local" / "bin" / ("datalad.exe" if sys.platform == "win32" else "datalad")
    )
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


def dataset_label(path: Path, root: Path) -> str:
    return "the project folder" if path == root.resolve() else portable_path(path, root).as_posix()


def versions_panel(result: CatalogResult, on_changed: Callable[[], Awaitable[None]]) -> None:
    root = result.project.root
    roots = project_datasets(result.project.config, root.resolve())
    if not roots:
        return
    datalad = preferences.load().get(preferences.DATALAD)
    with panel("Data versions", "Saved on this computer, pushed and updated with DataLad") as head:
        if not datalad:
            note("Set the path to datalad on the Settings page to save, push and update the data.")
            return
        with head:
            save = ui.button("Save", icon="save").props("flat no-caps")
            update = ui.button("Update", icon="cloud_download").props("flat no-caps")
            push = ui.button("Push", icon="cloud_upload").props("flat no-caps")
        holder = ui.column().classes("w-full gap-2")
        with holder:
            ui.spinner()

    states: list[DatasetState] = []

    async def fill() -> None:
        found = await computed(dataset_states, roots)
        states[:] = found
        if holder.is_deleted:
            return
        holder.clear()
        with holder:
            versions_table(found, root)
            dataset_tools(found, root, datalad, fill, on_changed)

    async def act(button: ui.button, function: Callable, *args) -> list[Path] | None:
        button.props("loading")
        try:
            return await computed(function, root, *args, datalad)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return None
        finally:
            button.props(remove="loading")

    def open_save() -> None:
        changed = [(s.root, p) for s in states for p in s.changed]
        with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
            ui.label("Save the changes").classes("text-lg font-medium")
            if not changed:
                note("Nothing has changed since the last save.")
                ui.button("Close", on_click=dialog.close).props("flat no-caps").classes("self-end")
                dialog.open()
                return
            note(
                "DataLad saves these as a new version on this computer; Push then sends it to "
                "the sibling."
            )
            with ui.column().classes("w-full gap-0 max-h-60 overflow-auto"):
                for folder, path in changed:
                    where = dataset_label(folder, root)
                    ui.label(path if folder == root.resolve() else f"{where}: {path}").classes(
                        "font-mono text-sm"
                    )
            message = (
                ui.input("What changed", placeholder="Wave 3 exports of October")
                .props("outlined dense autofocus")
                .classes("w-full")
            )

            async def go() -> None:
                text = (message.value or "").strip()
                if not text:
                    ui.notify("Say in a few words what changed", type="warning")
                    return
                dialog.close()
                saved = await act(save, partial(run_data_save, author=look().who), text)
                if saved is not None:
                    ui.notify(f"Saved {len(saved)} dataset(s)")
                    await on_changed()

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Save", on_click=go)
        dialog.open()

    async def go_update() -> None:
        updated = await act(update, run_data_update)
        if updated is not None:
            ui.notify(f"Updated {len(updated)} dataset(s) and got the files the project reads")
            await on_changed()

    async def go_push() -> None:
        pushed = await act(push, run_data_push)
        if pushed is None:
            return
        done = f"Pushed {len(pushed)} dataset(s)"
        if unsaved := sum(len(s.changed) for s in states):
            done += f"; {unsaved} unsaved change(s) stay on this computer until you save them"
        ui.notify(done, multi_line=True)
        await on_changed()

    save.on_click(open_save)
    update.on_click(go_update)
    push.on_click(go_push)
    ui.timer(0, fill, once=True)


def versions_table(states: list[DatasetState], root: Path) -> None:
    columns = [
        col("dataset", "Dataset"),
        col("changed", "Unsaved changes", numeric=True),
        col("sibling", "Sibling"),
        col("ahead", "Not pushed", numeric=True),
        col("behind", "New on the sibling", numeric=True),
        col("here", "Here", numeric=True),
    ]
    rows = [
        {
            "dataset": dataset_label(s.root, root),
            "changed": len(s.changed),
            "sibling": s.sibling or "none, or several",
            "ahead": "never pushed" if s.sibling and s.ahead is None else (s.ahead or ""),
            "behind": s.behind or "",
            "here": f"{size_text(s.present)} of {size_text(s.total)}" if s.total else "",
        }
        for s in states
    ]
    table(columns, rows)
    note(
        "Save keeps the changes as a new version on this computer, Push sends saved versions and "
        "their data to the sibling, and Update merges what others pushed and gets the files the "
        "project reads. New on the sibling counts what the last Update saw. Here is how much of "
        "the dataset's file content is on this computer."
    )


def dataset_tools(
    states: list[DatasetState],
    root: Path,
    datalad: str,
    refill: Callable[[], Awaitable[None]],
    on_changed: Callable[[], Awaitable[None]],
) -> None:
    labels = {s.root: dataset_label(s.root, root) for s in states}
    with ui.row().classes("w-full items-center gap-2"):
        chosen = ui.select(labels, value=states[0].root, label="Dataset").classes("w-72")
        chosen.visible = len(states) > 1
        ui.button("History", icon="history", on_click=lambda: open_history(chosen.value)).props(
            "flat no-caps"
        )
        get = ui.button("Get everything", icon="download").props("flat no-caps")
        drop = ui.button("Free space", icon="cleaning_services").props("flat no-caps")

    async def act(button: ui.button, function: Callable, done: str) -> None:
        button.props("loading")
        try:
            await computed(function, chosen.value, datalad)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        finally:
            button.props(remove="loading")
        ui.notify(done)
        await refill()

    def confirm_drop() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[32rem] max-w-full"):
            ui.label("Free the space").classes("text-lg font-medium")
            note(
                f"This removes the file content of {labels[chosen.value]} from this computer; "
                "the files stay listed, and Get everything brings them back. DataLad leaves any "
                "file it cannot find a copy of elsewhere, such as on the sibling."
            )

            async def go() -> None:
                dialog.close()
                await act(drop, run_drop_dataset, "Freed the space")

            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
                ui.button("Free space", on_click=go)
        dialog.open()

    async def open_history(dataset: Path) -> None:
        found = await computed(run_history, dataset)
        with ui.dialog() as dialog, ui.card().classes("w-[48rem] max-w-full"):
            ui.label(f"History of {labels[dataset]}").classes("text-lg font-medium")
            note(
                f"The last {len(found)} saved versions, newest first. A version that datalad run "
                "saved, such as a prepare step's, can run again: its command writes its outputs "
                "anew and they are saved as a new version."
            )
            with ui.scroll_area().classes("h-96 w-full"):
                for saved in found:
                    with ui.row().classes("w-full items-center no-wrap gap-3 py-1"):
                        ui.label(saved.when[:16].replace("T", " ")).classes("lc-note shrink-0")
                        ui.label(saved.author).classes("lc-note shrink-0")
                        with ui.label(saved.title).classes("grow min-w-0"):
                            if saved.files:
                                ui.tooltip("\n".join(saved.files[:20])).classes(
                                    "whitespace-pre-line"
                                )
                        ui.label(f"{len(saved.files)} file(s)").classes("lc-note shrink-0")
                        if saved.ran:
                            ui.button(
                                "Rerun",
                                icon="replay",
                                on_click=lambda c=saved.commit: rerun_version(dialog, dataset, c),
                            ).props("flat dense no-caps")
            with ui.row().classes("w-full justify-end"):
                ui.button("Close", on_click=dialog.close).props("flat no-caps")
        dialog.open()

    async def rerun_version(dialog: ui.dialog, dataset: Path, commit: str) -> None:
        dialog.close()
        ui.notify("Running it again")
        try:
            await computed(run_rerun, root, dataset, commit, datalad)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        ui.notify("Ran it again and saved what it wrote")
        await on_changed()

    get.on_click(lambda: act(get, run_get_dataset, "Got the content"))
    drop.on_click(confirm_drop)


def versions_tooltip(states: list[DatasetState], root: Path) -> str:
    return "; ".join(f"{dataset_label(s.root, root)}: {state_text(s)}" for s in states)


async def clone_dialog(start: Path | None) -> Path | None:
    # Returns the cloned project's folder, with the files it reads already here.
    datalad = preferences.load().get(preferences.DATALAD)
    if not datalad:
        ui.notify("Set the path to datalad on the Settings page first", type="warning")
        return None
    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label("Clone a project").classes("text-lg font-medium")
        note(
            "A project kept in DataLad, such as one a labmate pushed to GIN, a server or a shared "
            "drive. labcatalog clones it into the folder, gets the files it reads and opens it."
        )
        url = ui.input("Where it is", placeholder="https://gin.g-node.org/lab/project").classes(
            "w-full"
        )
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            folder = ui.input("Into the folder", value=str(start or common.serving or "")).classes(
                "grow"
            )

            async def pick() -> None:
                found = await choose_path(
                    FOLDER, start=Path(folder.value) if folder.value else None
                )
                if found:
                    folder.value = str(found)

            ui.button("Choose", on_click=pick).props("flat no-caps")

        async def go() -> None:
            if not (url.value or "").strip() or not folder.value:
                ui.notify("Give where the project is and a folder to put it in", type="warning")
                return
            where = Path(folder.value)
            if not allowed(where):
                ui.notify(f"Choose a folder inside {common.serving}", type="warning")
                return
            clone.props("loading")
            try:
                dialog.submit(await computed(run_clone, url.value.strip(), where, datalad))
            except LabCatalogError as err:
                ui.notify(str(err), type="negative", multi_line=True)
            finally:
                clone.props(remove="loading")

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat no-caps")
            clone = ui.button("Clone", on_click=go)
    try:
        return await dialog
    finally:
        dialog.delete()
