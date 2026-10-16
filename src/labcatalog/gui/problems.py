from collections.abc import Callable
from pathlib import Path

from nicegui import ui

from labcatalog.gui.common import col, keyed, note, open_path, split_location, table
from labcatalog.issues import Issue, summarize_issues
from labcatalog.metadata import editing

COLUMNS = [
    col("level", "Level"),
    col("location", "File"),
    col("message", "Problem", sortable=False),
    col("code", "Code"),
]
LEVEL_FILTERS = {"all": "All", "error": "Errors", "warning": "Warnings"}

LEVEL_CELL = r"""
<q-td :props="props" class="whitespace-nowrap">
  <q-icon :name="{error: 'error', warning: 'warning', info: 'info'}[props.value]"
          :color="{error: 'negative', warning: 'orange-8', info: 'info'}[props.value]"
          size="xs" class="q-mr-xs" />
  {{ props.value }}
</q-td>
"""
# The click is emitted back to Python, which opens the file on the Edit page or in its own app.
LOCATION_CELL = r"""
<q-td :props="props">
  <a v-if="props.value" class="text-primary cursor-pointer"
     :title="props.row.in_editor ? 'Open on the Edit page' : 'Open in its own app'"
     @click="$parent.$emit('open_location', props.row)">
    <q-icon :name="props.row.in_editor ? 'edit_note' : 'open_in_new'" size="xs" class="q-mr-xs" />
    {{ props.value }}
  </a>
</q-td>
"""
CODE_CELL = r"""
<q-td :props="props" class="text-grey-6 font-mono">{{ props.value }}</q-td>
"""


def render(issues: list[Issue], root: Path, edit: Callable[[str, int | None], None]) -> None:
    with ui.row().classes("w-full items-center gap-4"):
        ui.label(summarize_issues(issues)).classes("text-lg")
        ui.space()
        level = ui.toggle(LEVEL_FILTERS, value="all").props("dense no-caps")
        search = ui.input(placeholder="Search").props("dense clearable").classes("w-64")
    note("Project files open on the Edit page at the line named; data files open in their own app.")
    shown = issue_table(issues, root, edit)
    search.bind_value_to(shown, "filter")
    level.on_value_change(
        lambda e: shown.update_rows(
            keyed(issue_rows(issues, None if e.value == "all" else e.value, editable_paths(root)))
        )
    )


def issue_table(
    issues: list[Issue], root: Path, edit: Callable[[str, int | None], None]
) -> ui.table:
    editable = editable_paths(root)

    def follow(location: str) -> None:
        path, line = split_location(location)
        if path in editable:
            edit(path, line)
        else:
            open_path(root / path)

    shown = table(COLUMNS, issue_rows(issues, None, editable))
    shown.add_slot("body-cell-level", LEVEL_CELL)
    shown.add_slot("body-cell-location", LOCATION_CELL)
    shown.add_slot("body-cell-code", CODE_CELL)
    shown.on("open_location", lambda e: follow(e.args["location"]))
    return shown


def editable_paths(root: Path) -> set[str]:
    return {path for group in editing.editable_files(root).values() for path in group}


def issue_rows(issues: list[Issue], level: str | None, editable: set[str]) -> list[dict]:
    return [
        issue.model_dump() | {"in_editor": split_location(issue.location or "")[0] in editable}
        for issue in issues
        if level is None or issue.level == level
    ]
