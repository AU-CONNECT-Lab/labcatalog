from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import ui

from labcatalog import defaults
from labcatalog.data.check import CheckReport
from labcatalog.gui.common import col, keyed, note, open_path, split_location, table
from labcatalog.issues import Issue, summarize_issues
from labcatalog.metadata import accepted, editing

COLUMNS = [
    col("level", "Level"),
    col("location", "File"),
    col("message", "Problem", sortable=False),
    col("code", "Code"),
]
FIX_COLUMN = col("fix", "", sortable=False)
LEVEL_FILTERS = {"all": "All", "error": "Errors", "warning": "Warnings"}

LEVEL_CELL = r"""
<q-td :props="props" class="whitespace-nowrap">
  <span :class="'lc-pill lc-' + {error: 'bad', warning: 'warn', info: 'info'}[props.value]">
    {{ props.value }}
  </span>
</q-td>
"""
# The click is emitted back to Python, which opens the file on the Edit page or in its own app.
LOCATION_CELL = r"""
<q-td :props="props" class="whitespace-nowrap">
  <a v-if="props.value" class="text-primary cursor-pointer"
     :title="props.row.in_editor ? 'Open on the Edit page' : 'Open in its own app'"
     @click="$parent.$emit('open_location', props.row)">
    <q-icon :name="props.row.in_editor ? 'edit_note' : 'open_in_new'" size="xs" class="q-mr-xs" />
    {{ props.value }}
  </a>
</q-td>
"""
CODE_CELL = r"""
<q-td :props="props" class="lc-faint font-mono">{{ props.value }}</q-td>
"""
FIX_CELL = r"""
<q-td :props="props" class="text-right whitespace-nowrap">
  <q-btn flat dense no-caps no-wrap color="primary" icon="build" label="Fix"
         @click="$parent.$emit('fix', props.row)" />
</q-td>
"""


def render(
    report: CheckReport,
    root: Path,
    edit: Callable[[str, int | None], None],
    fix: Callable[[Issue], None],
    shown_again: Callable[[], Awaitable[None]],
) -> None:
    issues = report.issues
    with ui.row().classes("w-full items-center gap-4"):
        ui.label(summarize_issues(issues)).classes("text-lg")
        ui.space()
        level = ui.toggle(LEVEL_FILTERS, value="all").props("dense no-caps")
        search = ui.input(placeholder="Search").props("dense clearable").classes("w-64")
    note(
        "Fix opens a panel that says what the problem means and who usually fixes it. Project "
        "files open on the Edit page at the line named; data files open in their own app."
    )
    shown = issue_table(issues, root, edit, fix)
    search.bind_value_to(shown, "filter")
    level.on_value_change(
        lambda e: shown.update_rows(
            keyed(issue_rows(issues, None if e.value == "all" else e.value, editable_paths(root)))
        )
    )
    if report.accepted:
        accepted_section(report.accepted, root, shown_again)


def accepted_section(
    hidden: list[Issue], root: Path, shown_again: Callable[[], Awaitable[None]]
) -> None:
    entries = accepted.load(root, [])

    async def show_again(issue: Issue) -> None:
        accepted.withdraw(root, issue)
        await shown_again()

    with ui.expansion(
        f"{len(hidden)} warning(s) accepted as fine, in {defaults.ACCEPTED_FILENAME}"
    ).classes("w-full mt-4"):
        for issue in hidden:
            entry = next(e for e in entries if accepted.matches(issue, e))
            with ui.row().classes("w-full items-start no-wrap gap-4 lc-group"):
                with ui.column().classes("grow gap-0 min-w-0"):
                    ui.label(issue.message)
                    note(f"{issue.location or ''} · {issue.code}")
                    note(f"{entry.by}, {entry.date}: {entry.reason}")
                ui.button("Show again", on_click=lambda i=issue: show_again(i)).props(
                    "flat dense no-caps"
                )


def issue_table(
    issues: list[Issue],
    root: Path,
    edit: Callable[[str, int | None], None],
    fix: Callable[[Issue], None] | None = None,
) -> ui.table:
    editable = editable_paths(root)
    columns = [*COLUMNS, FIX_COLUMN] if fix else COLUMNS
    shown = table(columns, issue_rows(issues, None, editable))
    shown.add_slot("body-cell-level", LEVEL_CELL)
    shown.add_slot("body-cell-location", LOCATION_CELL)
    shown.add_slot("body-cell-code", CODE_CELL)
    shown.on("open_location", lambda e: follow(root, e.args["location"], edit))
    if fix:
        shown.add_slot("body-cell-fix", FIX_CELL)
        shown.on("fix", lambda e: fix(issues[e.args["n"]]))
    return shown


def follow(root: Path, location: str, edit: Callable[[str, int | None], None]) -> None:
    path, line = split_location(location)
    if path in editable_paths(root):
        edit(path, line)
    else:
        open_path(root / path)


def editable_paths(root: Path) -> set[str]:
    return {path for group in editing.editable_files(root).values() for path in group}


def issue_rows(issues: list[Issue], level: str | None, editable: set[str]) -> list[dict]:
    # n points back into issues, whatever the filter leaves out.
    return [
        issue.model_dump(exclude={"details"})
        | {"n": n, "in_editor": split_location(issue.location or "")[0] in editable}
        for n, issue in enumerate(issues)
        if level is None or issue.level == level
    ]
