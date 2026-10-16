from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from nicegui import run, ui

from labcatalog.data.prepare import Session, run_steps
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences
from labcatalog.gui.common import note, split_location
from labcatalog.issues import Issue
from labcatalog.metadata import accepted
from labcatalog.pipeline import CatalogResult

YOU = "You can fix this yourself."
SETTINGS = (
    "Whoever knows what the value should be; once you know, fix it on the Edit page at the "
    "line named."
)
SCRIPTS = (
    "The person who looks after the cleaning scripts: labcatalog never changes data files, "
    "so the fix goes into the script that makes this file. Copy a note for them below."
)
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
        SETTINGS,
    ),
    "unknown_reference": (
        "Something names an ID that does not exist, often a typo in the ID.",
        SETTINGS,
    ),
    "duplicate_id": ("Two things share one ID; one of them needs another.", SETTINGS),
    "invalid_value": ("A value that cannot work as written.", SETTINGS),
    "map_missing": (
        "A dataset has instruments but no column map; add the dataset again with Add a dataset "
        "on the Datasets page, or import its codebook.",
        YOU,
    ),
    "unmapped_item": (
        "Items of an instrument given in this dataset have no column in its map. Either the "
        "column is there under another name, or the item was not asked this time.",
        SETTINGS,
    ),
    "missing_code_collision": (
        "A response option has the same value as a missing code, so labcatalog cannot tell an "
        "answer from no answer.",
        SETTINGS,
    ),
    "reference_missing": ("The reference key is not in references.bib.", SETTINGS),
    "pdf_missing": ("The reference's PDF is not where the instrument says.", SETTINGS),
    "column_missing": (
        "The column map names a column the data file does not have, often a renamed column.",
        SETTINGS,
    ),
    "column_unmapped": (
        "The data file has columns the column map does not list, so labcatalog does not know "
        "what they are.",
        SETTINGS,
    ),
    "unexpected_value": (
        "Values that are neither response options nor missing codes. Either the data have a "
        "typo, or the value is real and the instrument or the missing codes leave it out.",
        SCRIPTS,
    ),
    "id_missing": ("Rows without an ID.", SCRIPTS),
    "id_whitespace": ("IDs with a space before or after them.", SCRIPTS),
    "id_pattern": ("IDs that do not look like the project's IDs.", SCRIPTS),
    "id_duplicate": ("The same ID appears more than once in one file.", SCRIPTS),
    "group_missing": ("IDs from which no family or group can be read.", SCRIPTS),
    "excluded_present": ("Rows of people on the exclusion list are still in the data.", SCRIPTS),
    "possible_identifier": (
        "A column that may hold names, emails, phone numbers, addresses or birth dates. It "
        "should not be in the data the catalog reads.",
        SCRIPTS,
    ),
    "date_unparseable": ("Dates that are not written the way the project expects.", SCRIPTS),
    "same_answer": (
        "People who gave the same answer to every item; they may have answered without "
        "reading.",
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


def note_text(issue: Issue) -> str:
    where = f" in {issue.location}" if issue.location else ""
    return f"labcatalog found a problem{where} ({issue.level}, {issue.code}):\n{issue.message}"


def open_fix(result: CatalogResult, issue: Issue, actions: FixActions) -> None:
    root = result.project.root if result.project else None
    what, who = EXPLAIN.get(issue.code, ("", SETTINGS))

    async def run_step() -> None:
        step = issue.details["step"]
        status.set_text(f"Running {step}")
        tools = preferences.load()
        try:
            runs = await run.io_bound(
                run_steps,
                result.project,
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

    def copy_note() -> None:
        ui.clipboard.write(note_text(issue))
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
        status = ui.label().classes("lc-bad-text")
        log = ui.column().classes("w-full")
        if issue.level == "warning" and root is not None:
            why = ui.input("Why it is fine", placeholder="e.g. checked the paper forms").classes(
                "w-full"
            )
        with ui.row().classes("w-full items-center gap-2"):
            if issue.code in PREPARE and issue.details.get("step"):
                ui.button(f"Run {issue.details['step']} again", icon="play_arrow", on_click=run_step)
            if issue.location:
                path, _ = split_location(issue.location)
                ui.button(f"Open {path}", icon="open_in_new").props("flat").on(
                    "click", lambda: (dialog.close(), actions.follow(issue.location))
                )
            ui.button("Copy a note", icon="content_copy", on_click=copy_note).props("flat")
            ui.space()
            if issue.level == "warning" and root is not None:
                ui.button("It is fine", icon="check", on_click=accept).props("flat")
            ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()
