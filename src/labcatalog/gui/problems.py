from pathlib import Path

from nicegui import ui

from labcatalog.gui.common import col, keyed, location_path, open_path, table
from labcatalog.issues import Issue, summarize_issues

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
# The click is emitted back to Python, which opens the file with the system's default app.
LOCATION_CELL = r"""
<q-td :props="props">
  <a v-if="props.value" class="text-primary cursor-pointer"
     @click="$parent.$emit('open_location', props.row)">{{ props.value }}</a>
</q-td>
"""
CODE_CELL = r"""
<q-td :props="props" class="text-grey-6 font-mono">{{ props.value }}</q-td>
"""


def render(issues: list[Issue], root: Path) -> None:
    with ui.row().classes("w-full items-center gap-4"):
        ui.label(summarize_issues(issues)).classes("text-lg")
        ui.space()
        level = ui.toggle(LEVEL_FILTERS, value="all").props("dense no-caps")
        search = ui.input(placeholder="Search").props("dense clearable").classes("w-64")
    shown = issue_table(issues, root)
    search.bind_value_to(shown, "filter")
    level.on_value_change(
        lambda e: shown.update_rows(
            keyed(issue_rows(issues, None if e.value == "all" else e.value))
        )
    )


def issue_table(issues: list[Issue], root: Path) -> ui.table:
    shown = table(COLUMNS, issue_rows(issues, None))
    shown.add_slot("body-cell-level", LEVEL_CELL)
    shown.add_slot("body-cell-location", LOCATION_CELL)
    shown.add_slot("body-cell-code", CODE_CELL)
    shown.on("open_location", lambda e: open_path(location_path(root, e.args["location"])))
    return shown


def issue_rows(issues: list[Issue], level: str | None) -> list[dict]:
    return [issue.model_dump() for issue in issues if level is None or issue.level == level]
