from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from nicegui import ui

from labcatalog.data import id_map
from labcatalog.gui import id_fix
from labcatalog.gui.common import empty, note, panel
from labcatalog.issues import Issue
from labcatalog.pipeline import CatalogResult

# The problems one data file's IDs can have, in the order they are shown.
CODES = {
    "id_missing": "no ID",
    "id_whitespace": "spaces",
    "id_pattern": "not in the ID pattern",
    "id_duplicate": "repeated",
    "id_not_in_roster": "not in the roster",
    "group_missing": "no group",
}


@dataclass
class IdRow:
    dataset: str
    study: str
    rows: int
    ids: int
    # Rows with each problem, by code.
    problems: dict[str, int] = field(default_factory=dict)
    corrected: int = 0


def id_rows(result: CatalogResult) -> list[IdRow]:
    by_dataset: dict[str, list[Issue]] = {}
    for issue in result.report.issues:
        if issue.code in CODES and "dataset" in issue.details:
            by_dataset.setdefault(issue.details["dataset"], []).append(issue)
    corrections = id_map.read(result.project.root)
    found = []
    for name, loaded in result.datasets.items():
        ids = loaded.frame[loaded.id_column]
        row = IdRow(name, loaded.config.study, len(ids), ids.nunique())
        for issue in by_dataset.get(name, []):
            row.problems[issue.code] = len(issue.details.get("rows", []))
        row.problems = {c: row.problems[c] for c in CODES if c in row.problems}
        row.corrected = int((corrections["dataset"] == name).sum())
        found.append(row)
    return found


def roster_issues(result: CatalogResult) -> list[Issue]:
    # A roster's own ID problems, which Fix IDs does not change.
    return [i for i in result.report.issues if i.code in CODES and "dataset" not in i.details]


def waiting(result: CatalogResult) -> int:
    return sum(bool(row.problems) for row in id_rows(result))


def render(
    result: CatalogResult,
    on_saved: Callable[[], Awaitable[None]],
    open_problems: Callable[[], None],
) -> None:
    rows = id_rows(result)
    with panel("Check IDs", "Each data file's IDs against the ID pattern and the study's roster"):
        note(
            "Fix IDs corrects IDs by rules, such as removing a prefix or a suffix, padding the "
            "number with zeros or a find and replace, and by hand; it shows which IDs are still "
            "not right after the rules. The corrections go to id_map.csv and the data files stay "
            "as they are. Rows that are not responses at all, such as test runs, belong in the "
            "cleaning step instead."
        )
        if not rows:
            empty("No data files read yet.")
            return
        for row in rows:
            with ui.row().classes("w-full items-center gap-3"):
                ui.label(row.dataset).classes("font-medium")
                ui.label(f"{row.study}, {row.rows} rows, {row.ids} IDs").classes("lc-note")
                for code, count in row.problems.items():
                    ui.label(f"{count} {CODES[code]}").classes("lc-pill lc-warn")
                if not row.problems:
                    ui.label("All right").classes("lc-pill lc-ok")
                if row.corrected:
                    ui.label(f"{row.corrected} corrected").classes("lc-pill lc-info")
                ui.space()
                ui.button(
                    "Fix IDs",
                    icon="badge",
                    on_click=lambda name=row.dataset: id_fix.open_dialog(result, name, on_saved),
                ).props("flat dense no-caps")
        if rosters := roster_issues(result):
            with ui.row().classes("w-full items-center gap-2"):
                note(
                    f"The rosters have {len(rosters)} ID problem(s) of their own; correct them in "
                    "the roster file."
                )
                ui.button("See them in Problems", on_click=open_problems).props(
                    "flat dense no-caps"
                )
