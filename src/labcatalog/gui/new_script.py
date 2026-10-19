from collections.abc import Awaitable, Callable

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, note, path_input
from labcatalog.gui.files import FILE, FOLDER, choose_path
from labcatalog.metadata import changes, scoring_steps
from labcatalog.metadata.scripts import LANGUAGES, STAGE_HELP, STAGES, new_script, step_change
from labcatalog.metadata.stage_scripts import stage_script
from labcatalog.paths import portable_path, posix_str
from labcatalog.pipeline import CatalogResult

OTHER = "other"
DATABASE = "database"


def open_dialog(result: CatalogResult, on_made: Callable[[str], Awaitable[None]]) -> None:
    # A script for a stage starts written for this project, with its step; any other is bare.
    project = result.project
    root = project.root
    files = [d.name for d in project.config.datasets if d.path]
    given = sorted({(v.instrument_id, v.dataset) for v in result.catalog.variables})
    choices = {k: f"{STAGES[k]}: {v}" for k, v in STAGE_HELP.items()}
    choices = {
        "clean": choices.pop("clean"),
        DATABASE: "From a database: a query whose rows become a dataset's file",
        **choices,
    }
    choices[OTHER] = "Other: a script with only the lines that read and write its files"
    fields: dict[str, ui.element] = {}

    def picker(label: str, hint: str, kind: str) -> ui.input:
        with ui.row().classes("w-full items-start no-wrap gap-2"):
            found = path_input(label, "", hint)

            async def choose() -> None:
                chosen = await choose_path(kind, start=root)
                if chosen:
                    found.set_value(posix_str(portable_path(chosen, root)))

            ui.button("Choose", on_click=choose).props("flat no-caps")
        return found

    @ui.refreshable
    def details() -> None:
        fields.clear()
        stage = stage_select.value
        if stage in ("clean", "extract", DATABASE):
            fields["dataset"] = (
                ui.select(files, label="Dataset it writes", with_input=True)
                .props("outlined dense")
                .classes("w-full")
            )
            if stage == "clean":
                fields["source"] = picker("Raw export", "A file in the project, such as raw/", FILE)
            elif stage == DATABASE:
                fields["source"] = picker(
                    "Database", "A SQLite or DuckDB file in the project", FILE
                )
            else:
                fields["source"] = picker(
                    "Pipeline output", "The folder with one file per person", FOLDER
                )
        elif stage == "process":
            fields["name"] = ui.input("Name", placeholder="process_eeg_w1").classes("w-full")
            fields["source"] = picker("Recordings", "The folder of raw recordings", FOLDER)
            fields["target"] = picker(
                "Output folder", "Where the pipeline writes, such as derivatives/", FOLDER
            )
        elif stage == "score":
            fields["pair"] = (
                ui.select(
                    {f"{i}|{d}": f"{i} in {d}" for i, d in given},
                    label="Instrument and dataset",
                    with_input=True,
                )
                .props("outlined dense")
                .classes("w-full")
            )
        else:
            fields["name"] = ui.input("Name", placeholder="tidy_up").classes("w-full")
        if stage == "score":
            note(
                "The scoring script of the instrument's page: its scores' columns are listed in it."
            )
        elif stage != OTHER:
            note(
                "The script tells what it reads and writes, with the dataset's ID column, columns and "
                "missing codes, and leaves one function, or a database's query, to fill in. Its step "
                "is added too."
            )

    async def create() -> None:
        stage, language = stage_select.value, language_select.value

        def value(key: str) -> str:
            return (fields[key].value or "").strip() if key in fields else ""

        try:
            if stage == OTHER:
                path = new_script(root, value("name"), language)
            elif stage == "score":
                if not value("pair"):
                    raise LabCatalogError("Choose the instrument and the dataset")
                instrument, dataset = value("pair").split("|")
                path = scoring_steps.start_script(
                    project, result.catalog, instrument, dataset, language
                )
                scoring_steps.register(project, instrument, dataset, path)
            else:
                made = stage_script(
                    project,
                    stage,
                    language,
                    value("source"),
                    value("target"),
                    value("dataset") or None,
                    value("name"),
                )
                change = step_change(project, None, made.step)
                issues = await computed(changes.check, project, [change])
                if issues:
                    raise LabCatalogError("; ".join(i.message for i in issues))
                (root / made.path).parent.mkdir(parents=True, exist_ok=True)
                (root / made.path).write_text(made.text, encoding="utf-8")
                changes.write(project, [change])
                path = made.path
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        dialog.close()
        ui.notify(f"Wrote {path}")
        await on_made(path)

    with ui.dialog() as dialog, ui.card().classes("w-[40rem] max-w-full"):
        ui.label("New script").classes("text-lg font-medium")
        stage_select = (
            ui.select(choices, value="clean", label="Stage", on_change=lambda: details.refresh())
            .props("outlined dense")
            .classes("w-full")
        )
        language_select = ui.toggle({k: v.name for k, v in LANGUAGES.items()}, value="r").props(
            "dense no-caps"
        )
        details()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat no-caps")
            ui.button("Create", on_click=create)
    dialog.open()
