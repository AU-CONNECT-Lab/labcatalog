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
    modality: str
    rows: int
    ids: int
    # Rows with each problem, by code.
    problems: dict[str, int] = field(default_factory=dict)
    # The IDs as the file writes them, for each problem; lines of the file for rows with none.
    shown: dict[str, list[str]] = field(default_factory=dict)
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
        row = IdRow(name, loaded.config.study, loaded.config.modality, len(ids), ids.nunique())
        typed = loaded.original_ids if loaded.original_ids is not None else ids
        for issue in by_dataset.get(name, []):
            rows = issue.details.get("rows", [])
            row.problems[issue.code] = len(rows)
            row.shown[issue.code] = shown_ids(issue.code, typed, rows)
        row.problems = {c: row.problems[c] for c in CODES if c in row.problems}
        row.corrected = int((corrections["dataset"] == name).sum())
        found.append(row)
    return found


def shown_ids(code: str, typed, rows: list[int]) -> list[str]:
    if code == "id_missing":
        # Line 1 is the header, so the first row below it is line 2.
        return [f"line {n + 2}" for n in rows]
    values = dict.fromkeys(typed.loc[rows])
    return [repr(v) if v != v.strip() else v for v in values]


def roster_issues(result: CatalogResult) -> list[Issue]:
    # A roster's own ID problems, which Fix IDs does not change.
    return [i for i in result.report.issues if i.code in CODES and "dataset" not in i.details]


def grouped(result: CatalogResult, rows: list[IdRow]) -> dict[str, dict[str, list[IdRow]]]:
    # The files with problems, by study, then by modality, each in the project's order.
    config = result.project.config
    order = {m: n for n, m in enumerate(config.vocab.modalities)}
    found: dict[str, dict[str, list[IdRow]]] = {}
    for study in config.studies:
        mine = [r for r in rows if r.study == study and r.problems]
        for row in sorted(mine, key=lambda r: order.get(r.modality, len(order))):
            found.setdefault(study, {}).setdefault(row.modality, []).append(row)
    return found


def waiting(result: CatalogResult) -> int:
    return sum(bool(row.problems) for row in id_rows(result))


def render(
    result: CatalogResult,
    on_saved: Callable[[], Awaitable[None]],
    open_problems: Callable[[], None],
) -> None:
    config = result.project.config
    rows = id_rows(result)

    def line(row: IdRow) -> None:
        with ui.row().classes("w-full items-center gap-3"):
            ui.label(row.dataset).classes("font-medium")
            ui.label(f"{row.rows} rows, {row.ids} IDs").classes("lc-note")
            for code, count in row.problems.items():
                ui.label(f"{count} {CODES[code]}").classes("lc-pill lc-warn")
                ui.label(", ".join(row.shown.get(code, []))).classes("lc-note")
            if row.corrected:
                ui.label(f"{row.corrected} corrected").classes("lc-pill lc-info")
            ui.space()
            ui.button(
                "Fix IDs",
                icon="badge",
                on_click=lambda: id_fix.open_dialog(result, row.dataset, on_saved),
            ).props("flat dense no-caps")

    with panel(
        "Check IDs",
        help_text="Fix IDs corrects IDs by rules or by hand. The corrections go to id_map.csv; "
        "the data files stay as they are.",
    ):
        if not rows:
            empty("No data files read yet.")
            return
        for study, modalities in grouped(result, rows).items():
            ui.label(config.studies[study].label or study).classes("lc-subhead")
            for modality, found in modalities.items():
                ui.label(config.vocab.modality_label(modality)).classes("lc-facet")
                for row in found:
                    line(row)
        fine = [r for r in rows if not r.problems]
        if len(fine) == len(rows):
            ui.label(f"All {len(rows)} data files' IDs are right.").classes("lc-pill lc-ok w-fit")
        elif fine:
            with ui.expansion(f"{len(fine)} files with no ID problems").classes("w-full"):
                for row in fine:
                    line(row)
        if rosters := roster_issues(result):
            with ui.row().classes("w-full items-center gap-2"):
                note(
                    f"The rosters have {len(rosters)} ID problem(s) of their own; correct them in "
                    "the roster file."
                )
                ui.button("See them in Problems", on_click=open_problems).props(
                    "flat dense no-caps"
                )
