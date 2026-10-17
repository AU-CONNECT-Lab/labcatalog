from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from nicegui import ui

from labcatalog.codebook.core import holds
from labcatalog.config import dataset_by_name
from labcatalog.data.prepare import Session, run_steps
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences
from labcatalog.gui.common import caption, col, computed, note, split_location, table
from labcatalog.issues import Issue
from labcatalog.metadata import accepted, changes, fixes
from labcatalog.metadata.changes import Change
from labcatalog.pipeline import CatalogResult
from labcatalog.project import Project, load_project

YOU = "You can fix this yourself."
SETTINGS = (
    "Whoever knows what the value should be; once you know, fix it on the Edit page at the "
    "line named."
)
SCRIPTS = (
    "The person who looks after the cleaning scripts: labcatalog never changes data files, "
    "so the fix goes into the script that makes this file. Copy a note for them below."
)
PICK = "If you know the right answer, fix it below; if not, ask whoever looks after the settings."
LOOK = "Nobody may need to: look at it, and if it is fine, record that below so it stops showing."

# What each problem means in plain words, and who usually fixes it.
EXPLAIN: dict[str, tuple[str, str]] = {
    "yaml_syntax": (
        "The file cannot be read: often a misplaced colon, a tab used for indentation, or an "
        "unclosed quote or bracket.",
        YOU,
    ),
    "extra_forbidden": ("A key labcatalog does not know, usually a misspelling.", YOU),
    "missing": ("A key that must be there is missing.", SETTINGS),
    "map_encoding": (
        "The column map is not saved as UTF-8. In Excel, save it as 'CSV UTF-8'.",
        YOU,
    ),
    "map_header": ("The column map's first line must name column, instrument and item.", YOU),
    "map_row": (
        "A row of the column map has an instrument without an item, or the other way round.",
        YOU,
    ),
    "not_in_vocab": (
        "A modality, reporter or target that is not among the allowed words, often a typo.",
        PICK,
    ),
    "unknown_reference": (
        "Something names an ID that does not exist, often a typo in the ID.",
        PICK,
    ),
    "duplicate_id": (
        "Two things share one ID, or the column map lists one thing twice.",
        SETTINGS,
    ),
    "invalid_value": ("A value that cannot work as written.", SETTINGS),
    "map_missing": (
        "A dataset has instruments but no column map; add the dataset again with Add a dataset "
        "on the Datasets page, or import its codebook.",
        YOU,
    ),
    "unmapped_item": (
        "Items of an instrument given in this dataset have no column in its map. Either the "
        "column is there under another name, or the item was not asked this time.",
        PICK,
    ),
    "missing_code_collision": (
        "A response option has the same value as a missing code, so labcatalog cannot tell an "
        "answer from no answer.",
        PICK,
    ),
    "reference_missing": ("The reference key is not in references.bib, often a typo.", PICK),
    "pdf_missing": ("The reference's PDF is not where the instrument says.", SETTINGS),
    "column_missing": (
        "The column map names a column the data file does not have, often a renamed column.",
        PICK,
    ),
    "column_unmapped": (
        "The data file has columns the column map does not list, so labcatalog does not know "
        "what they are.",
        PICK,
    ),
    "wave_unclaimed": (
        "The file holds rows for a wave that no dataset reads: a new wave, or a wave written "
        "another way in the data than in the dataset's settings.",
        PICK,
    ),
    "unexpected_value": (
        "Values that are neither response options nor missing codes. Either the data have a "
        "typo, or the value is real and the instrument or the missing codes leave it out.",
        "A typo is fixed by the person who looks after the cleaning scripts, since labcatalog "
        "never changes data files; copy a note for them below. A real value you can record "
        "below.",
    ),
    "id_missing": ("Rows without an ID.", SCRIPTS),
    "id_whitespace": ("IDs with a space before or after them.", SCRIPTS),
    "id_pattern": ("IDs that do not look like the project's IDs.", SCRIPTS),
    "id_duplicate": ("The same ID appears more than once in one file.", SCRIPTS),
    "group_missing": ("IDs from which the group ID cannot be read.", SCRIPTS),
    "excluded_present": ("Rows of people on the exclusion list are still in the data.", SCRIPTS),
    "possible_identifier": (
        "A column that may hold names, emails, phone numbers, addresses or birth dates. It "
        "should not be in the data the catalog reads.",
        SCRIPTS,
    ),
    "date_unparseable": ("Dates that are not written the way the project expects.", SCRIPTS),
    "same_answer": (
        "People who gave the same answer to every item; they may have answered without reading.",
        LOOK,
    ),
    "score_mismatch": (
        "A score in the data differs from the score labcatalog computes.",
        SETTINGS,
    ),
    "score_coverage": (
        "Some rows have a score in the data but not in labcatalog's, or the other way round.",
        SETTINGS,
    ),
    "prepare_output_missing": ("A cleaning step's output file does not exist yet.", YOU),
    "prepare_outdated": (
        "A cleaning step's output is older than its input, so the data the catalog reads are "
        "not the newest.",
        YOU,
    ),
}
PREPARE = ("prepare_outdated", "prepare_output_missing")


@dataclass
class FixActions:
    follow: Callable[[str], None]
    reload: Callable[[], Awaitable[None]]
    root: Path
    # Opens Add a dataset repeating a dataset for a wave.
    add_dataset: Callable[[str, str], None]


def note_text(issue: Issue, rows: list[dict[str, str]]) -> str:
    where = f" in {issue.location}" if issue.location else ""
    lines = [f"labcatalog found a problem{where} ({issue.level}, {issue.code}):", issue.message]
    lines += [", ".join(f"{k} {v}" for k, v in row.items()) for row in rows]
    return "\n".join(lines)


def rows_of(result: CatalogResult, issue: Issue) -> list[dict[str, str]]:
    loaded = result.datasets.get(issue.details.get("dataset", ""))
    return fixes.evidence(loaded, issue) if loaded and "rows" in issue.details else []


def rows_section(issue: Issue, rows: list[dict[str, str]]) -> None:
    caption("The rows")
    columns = [col("row", "Row", numeric=True), col("id", "ID")]
    if any("value" in row for row in rows):
        columns.append(col("value", issue.details.get("column", "Value")))
    table(columns, rows).classes(remove="w-full")
    more = len(issue.details["rows"]) - len(rows)
    note(
        "Rows count from the first line below the header of the data file."
        + (f" {more} more rows are not shown." if more > 0 else "")
    )


def open_fix(result: CatalogResult, issue: Issue, actions: FixActions) -> None:
    root = actions.root
    project = result.project or loaded(root)
    what, who = EXPLAIN.get(issue.code, ("", SETTINGS))

    async def run_step() -> None:
        step = issue.details["step"]
        status.set_text(f"Running {step}")
        tools = preferences.load()
        try:
            runs = await computed(
                run_steps,
                project,
                [step],
                Session(),
                False,
                None,
                tools.get(preferences.RSCRIPT),
                tools.get(preferences.DATALAD),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        if runs and runs[-1].exit_code != 0:
            status.set_text(f"{step} stopped with an error; show this to whoever wrote the script.")
            with log:
                ui.code("\n".join(runs[-1].log), language=None).classes("w-full lc-wrap")
            return
        dialog.close()
        await actions.reload()

    async def accept() -> None:
        reason = (why.value or "").strip()
        if not reason:
            status.set_text("Say in a few words why it is fine, for whoever reads it later.")
            return
        accepted.accept(root, issue, reason)
        dialog.close()
        await actions.reload()

    async def save(found: list[Change], anyway: bool = False) -> None:
        problems = [] if anyway else changes.check(project, found)
        if problems:
            # Often a problem the first one hid, such as a typo in an administration skipped so far.
            status.set_text(
                "After this change labcatalog would report: "
                + "; ".join(i.message for i in problems)
                + ". If that was already wrong before, save anyway and fix it next."
            )
            log.clear()
            with log:
                ui.button("Save anyway", on_click=lambda: save(found, True)).props("flat")
            return
        try:
            changes.write(project, found)
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        dialog.close()
        await actions.reload()

    def follow() -> None:
        dialog.close()
        actions.follow(issue.location)

    def add_dataset(wave: str) -> None:
        dialog.close()
        actions.add_dataset(issue.details["dataset"], wave)

    def copy_note() -> None:
        ui.clipboard.write(note_text(issue, rows))
        ui.notify("Note copied")

    with ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full gap-3"):
        with ui.row().classes("items-center gap-2"):
            kind = {"error": "lc-bad", "warning": "lc-warn"}.get(issue.level, "lc-info")
            ui.label(issue.level).classes(f"lc-pill {kind}")
            ui.label(issue.code).classes("font-mono lc-faint")
        ui.label(issue.message).classes("font-medium")
        if what:
            ui.label(what)
        with ui.row().classes("items-start gap-2 no-wrap"):
            ui.icon("person_outline").classes("lc-faint mt-1")
            note(who)
        rows = rows_of(result, issue)
        if rows:
            rows_section(issue, rows)
        if project is not None and issue.code in REPAIRS:
            REPAIRS[issue.code](project, result, issue, save)
        status = ui.label().classes("lc-bad-text")
        log = ui.column().classes("w-full")
        if issue.level == "warning":
            why = ui.input("Why it is fine", placeholder="e.g. checked the paper forms").classes(
                "w-full"
            )
        with ui.row().classes("w-full items-center gap-2"):
            if issue.code in PREPARE and issue.details.get("step"):
                ui.button(
                    f"Run {issue.details['step']} again", icon="play_arrow", on_click=run_step
                )
            if issue.code == "wave_unclaimed" and project is not None:
                for wave in issue.details.get("waves", []):
                    ui.button(
                        f"Add a dataset for wave {wave}",
                        icon="add",
                        on_click=lambda wave=wave: add_dataset(wave),
                    )
            if issue.location:
                ui.button(
                    f"Open {split_location(issue.location)[0]}", icon="open_in_new", on_click=follow
                ).props("flat")
            ui.button("Copy a note", icon="content_copy", on_click=copy_note).props("flat")
            ui.space()
            if issue.level == "warning":
                ui.button("It is fine", icon="check", on_click=accept).props("flat")
            ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def loaded(root: Path) -> Project | None:
    # A project whose files read but do not validate, so its mistakes can still be fixed here.
    try:
        return load_project(root)
    except LabCatalogError:
        return None


def unlisted_columns(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    dataset = issue.details["dataset"]
    items = {
        i: [item.id for item in project.instruments[i].items]
        for i in fixes.administered(project, dataset)
    }
    caption("Add to the column map")
    note("Leave Instrument empty for a column that is not an item, such as notes or a date.")
    picks = []
    for column in issue.details["columns"]:
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.label(column).classes("font-mono w-48")
            instrument = ui.select(
                {"": "not an item", **{i: i for i in items}}, value="", label="Instrument"
            ).classes("w-56")
            item = ui.select([], label="Item").classes("w-40")
            item.set_visibility(False)

            def chosen(e, item=item) -> None:
                item.set_options(items.get(e.value, []), value=None)
                item.set_visibility(bool(e.value))

            instrument.on_value_change(chosen)
            picks.append((column, instrument, item))

    async def add() -> None:
        if any(i.value and not t.value for _, i, t in picks):
            ui.notify("Pick the item for each column given an instrument", type="warning")
            return
        rows = [(column, i.value or "", t.value or "") for column, i, t in picks]
        await save([fixes.map_rows(project, dataset, rows)])

    ui.button("Add to the column map", icon="playlist_add", on_click=add)


def wrong_word(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    details = issue.details
    kind, value = details["vocab"], details["value"]
    words = list(getattr(project.config.vocab, kind))
    # The same slip copied into other entries, so one choice fixes them all.
    places = [
        i.details
        for i in result.report.issues
        if i.code == "not_in_vocab"
        and "field" in i.details
        and (i.details["vocab"], i.details["value"]) == (kind, value)
    ]
    caption("Fix the word")
    with ui.row().classes("items-center gap-3"):
        if "field" in details and words:
            choice = ui.select(words, value=fixes.closest(value, words), label="Change to").classes(
                "w-48"
            )

            async def replace(where: list[dict]) -> None:
                if choice.value:
                    await save(fixes.replace_word(project, where, choice.value))

            ui.button("Use this word", on_click=lambda: replace([details]))
            if len(places) > 1:
                ui.button(
                    f"Use it in all {len(places)} places", on_click=lambda: replace(places)
                ).props("flat")
        ui.button(
            f"Add '{value}' as a new word",
            on_click=lambda: save([fixes.add_to_vocab(project, kind, value)]),
        ).props("flat")


def unmapped_items(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    dataset, instrument = issue.details["dataset"], issue.details["instrument"]
    loaded = result.datasets.get(dataset)
    columns = fixes.free_columns(project, dataset, list(loaded.frame.columns) if loaded else [])
    choices = {
        "": "leave as it is",
        fixes.NOT_ASKED: f"not asked in {dataset}",
        **{c: c for c in columns},
    }
    caption("Where each item is")
    note(f"Pick the data column that holds the item, or record that {dataset} did not ask it.")
    picks = []
    for item in issue.details["items"]:
        guess = next((c for c in columns if holds(c, item)), "")
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.label(item).classes("font-mono w-40")
            picks.append((item, ui.select(choices, value=guess, label="Column").classes("w-64")))

    async def apply() -> None:
        rows = [
            (s.value, instrument, item) for item, s in picks if s.value not in ("", fixes.NOT_ASKED)
        ]
        dropped = [item for item, s in picks if s.value == fixes.NOT_ASKED]
        found = []
        if rows:
            found.append(fixes.map_rows(project, dataset, rows))
        if dropped:
            found.append(fixes.not_asked(project, dataset, instrument, dropped))
        if found:
            await save(found)

    ui.button("Save", icon="check", on_click=apply)


def stray_values(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    details = issue.details
    dataset = details["dataset"]
    variables = result.catalog.variables if result.catalog else []
    variable = next(
        (v for v in variables if (v.dataset, v.column) == (dataset, details["column"])), None
    )
    choices = {"": "a typo, to fix in the data", "missing": "a missing code"}
    if variable is not None and variable.response_set:
        choices["option"] = f"a new answer in {variable.response_set}"
    caption("What each value is")
    note(
        "A typo goes to whoever makes the data file (Copy a note). A value that means no "
        "answer, such as 99 for refused, is a missing code. A real answer the instrument leaves "
        "out is a new answer option, which changes the instrument for every dataset."
    )
    picks = []
    for value in details["values"]:
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.label(value).classes("font-mono w-24")
            kind = ui.select(choices, value="", label="It is").classes("w-64")
            label = ui.input("Label", placeholder="e.g. refused").classes("w-48")
            picks.append((value, kind, label))
    scope = ui.select(
        {"dataset": f"only in {dataset}", "all": "in every dataset"},
        value="dataset",
        label="New missing codes count",
    ).classes("w-64")

    async def apply() -> None:
        chosen = [(v, k.value, (t.value or "").strip()) for v, k, t in picks if k.value]
        if any(not label for _, _, label in chosen):
            ui.notify("Give each value a label, such as refused", type="warning")
            return
        codes = [(v, label) for v, kind, label in chosen if kind == "missing"]
        options = [(v, label) for v, kind, label in chosen if kind == "option"]
        found = []
        if codes:
            found.append(fixes.add_missing_codes(project, dataset, codes, scope.value == "all"))
        if options:
            instrument = details["instrument"]
            found.append(fixes.add_options(project, instrument, variable.response_set, options))
        if found:
            await save(found)

    ui.button("Save", icon="check", on_click=apply)


def wrong_id(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    details = issue.details
    if "path" not in details or not details["choices"]:
        note("This one has no single value to swap; open the file below to fix it.")
        return
    caption("Fix the ID")
    with ui.row().classes("items-center gap-3"):
        choice = ui.select(
            details["choices"],
            value=fixes.closest(details["value"], details["choices"]),
            label=f"Instead of {details['value']}",
        ).classes("w-64")

        async def replace() -> None:
            if choice.value:
                path, _ = split_location(issue.location)
                await save([fixes.replace_at(project, path, details["path"], choice.value)])

        ui.button("Use this ID", on_click=replace)


def missing_column(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    details = issue.details
    dataset, line = details["dataset"], details["line"]
    loaded = result.datasets.get(dataset)
    columns = fixes.free_columns(project, dataset, list(loaded.frame.columns) if loaded else [])
    caption("Fix the column")
    note(
        "Pick the name the column has in the data file now, or take the row out of the column "
        "map if the file does not hold it."
    )
    with ui.row().classes("items-center gap-3"):
        if columns:
            choice = ui.select(
                columns,
                value=fixes.closest(details["column"], columns),
                label=f"Instead of {details['column']}",
            ).classes("w-64")

            async def rename() -> None:
                if choice.value:
                    await save([fixes.map_line(project, dataset, line, choice.value)])

            ui.button("Use this column", on_click=rename)
        ui.button(
            "Take the row out",
            icon="delete",
            on_click=lambda: save([fixes.map_line(project, dataset, line, None)]),
        ).props("flat")


def repeated_row(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    details = issue.details
    if "lines" not in details:
        note("Give one of them another ID in the file below; other files may name it too.")
        return
    dataset = details["dataset"]
    lines = fixes.map_lines(project, dataset)
    caption("Keep one row")
    for n in details["lines"]:
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.label(f"Line {n}").classes("w-16 lc-faint")
            ui.label(lines[n - 1]).classes("font-mono w-72")
            ui.button(
                "Take this row out",
                icon="delete",
                on_click=lambda n=n: save([fixes.map_line(project, dataset, n, None)]),
            ).props("flat dense")


def clashing_code(project: Project, result: CatalogResult, issue: Issue, save) -> None:
    details = issue.details
    dataset, code = details["dataset"], details["value"]
    caption("Stop counting it as missing")
    note(
        f"If {code} is a real answer in {dataset}, take it out of the missing codes. If it "
        "really means no answer, the response set is wrong: open the instrument file below."
    )
    with ui.row().classes("items-center gap-3"):
        scope = None
        if dataset_by_name(project.config, dataset).missing_codes is None:
            scope = ui.select(
                {"dataset": f"only in {dataset}", "all": "in every dataset"},
                value="dataset",
                label="Take it out",
            ).classes("w-64")

        async def drop() -> None:
            everywhere = scope is not None and scope.value == "all"
            await save([fixes.drop_missing_code(project, dataset, code, everywhere)])

        ui.button(f"{code} is an answer", icon="check", on_click=drop)


REPAIRS = {
    "unknown_reference": wrong_id,
    "reference_missing": wrong_id,
    "column_missing": missing_column,
    "duplicate_id": repeated_row,
    "missing_code_collision": clashing_code,
    "unexpected_value": stray_values,
    "column_unmapped": unlisted_columns,
    "not_in_vocab": wrong_word,
    "unmapped_item": unmapped_items,
}
