from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from nicegui import ui

from labcatalog import defaults
from labcatalog.config import id_pattern
from labcatalog.data import id_map
from labcatalog.data.id_map import Row, Rule
from labcatalog.gui.common import note
from labcatalog.pipeline import CatalogResult
from labcatalog.sources import load_rosters

ALL = "all"
CHANGED = "changed"
PROBLEMS = "problems"
SHOWN = {ALL: "All", CHANGED: "Changed", PROBLEMS: "Not right yet"}
YES, NO = "✓", "✗"


@dataclass
class State:
    dataset: str
    rules: list[Rule] = field(default_factory=list)
    # IDs typed by hand, and the corrections saved before, which the rules leave alone.
    manual: dict[str, str] = field(default_factory=dict)
    shown: str = ALL


def open_dialog(
    result: CatalogResult, dataset: str | None, on_saved: Callable[[], Awaitable[None]]
) -> None:
    root = result.project.root
    names = [n for n, d in result.datasets.items() if d.original_ids is not None]
    state = State(dataset if dataset in names else names[0])
    state.manual = id_map.mapping(root, state.dataset)
    rosters = {
        study: set(r.frame[r.id_column].str.strip())
        for study, r in load_rosters(result.project).items()
    }

    def listed() -> set[str] | None:
        return rosters.get(result.datasets[state.dataset].config.study)

    def pattern() -> tuple[str | None, str]:
        # Each study can write its IDs its own way.
        return id_pattern(result.project.config, result.datasets[state.dataset].config.study)

    def rows() -> list[Row]:
        ids = result.datasets[state.dataset].original_ids
        ids = [v for v in ids.astype(str) if v != ""]
        return id_map.propose(ids, state.rules, state.manual, pattern()[0], listed())

    def wrong(row: Row) -> bool:
        return row.clash or row.matches is False or row.listed is False

    def choose_dataset(name: str) -> None:
        state.dataset = name
        state.manual = id_map.mapping(root, name)
        preview.refresh()

    def set_rule(i: int, key: str, value) -> None:
        setattr(state.rules[i], key, value)
        preview.refresh()
        if key == "kind":
            rules_view.refresh()

    def add_rule() -> None:
        state.rules.append(Rule(id_map.PREFIX))
        rules_view.refresh()
        preview.refresh()

    def drop_rule(i: int) -> None:
        state.rules.pop(i)
        rules_view.refresh()
        preview.refresh()

    def typed(e) -> None:
        old, new = e.args["data"]["old"], (e.args.get("newValue") or "").strip()
        if new:
            state.manual[old] = new
        else:
            state.manual.pop(old, None)
        preview.refresh()

    @ui.refreshable
    def rules_view() -> None:
        for i, rule in enumerate(state.rules):
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.select(
                    id_map.RULES,
                    value=rule.kind,
                    on_change=lambda e, i=i: set_rule(i, "kind", e.value),
                ).classes("w-56")
                if rule.kind in (id_map.PREFIX, id_map.SUFFIX, id_map.REPLACE):
                    label = "Find (regular expression)" if rule.kind == id_map.REPLACE else "Text"
                    ui.input(
                        label,
                        value=rule.text,
                        on_change=lambda e, i=i: set_rule(i, "text", e.value or ""),
                    ).classes("grow")
                if rule.kind == id_map.REPLACE:
                    ui.input(
                        "Replace with",
                        value=rule.replacement,
                        on_change=lambda e, i=i: set_rule(i, "replacement", e.value or ""),
                    ).classes("grow")
                if rule.kind == id_map.PAD:
                    ui.number(
                        "Digits",
                        value=rule.width,
                        min=1,
                        max=12,
                        format="%d",
                        on_change=lambda e, i=i: set_rule(i, "width", int(e.value or 1)),
                    ).classes("w-28")
                ui.space()
                ui.button(icon="close", on_click=lambda i=i: drop_rule(i)).props(
                    "flat round dense"
                ).tooltip("Remove this rule")
        ui.button("Add a rule", icon="add", on_click=add_rule).props("flat dense no-caps")

    @ui.refreshable
    def preview() -> None:
        problem = id_map.rule_problem(state.rules)
        if problem:
            note(problem)
            save_button.disable()
            return
        found = rows()
        changed = [r for r in found if r.new != r.old]
        clashes = [r for r in found if r.clash]
        parts = [f"{len(changed)} of {len(found)} IDs change"]
        if pattern()[0]:
            parts.append(f"{sum(r.matches is False for r in found)} do not match {pattern()[1]}")
        if listed() is not None:
            parts.append(f"{sum(r.listed is False for r in found)} are not in the roster")
        if clashes:
            parts.append(f"{len(clashes)} would become the same ID as another")
        ui.label("; ".join(parts) + ".").classes("lc-note")
        shown = {
            # What needs a look first: IDs still wrong, then IDs that change.
            ALL: sorted(found, key=lambda r: (not wrong(r), r.new == r.old)),
            CHANGED: changed,
            PROBLEMS: [r for r in found if wrong(r)],
        }[state.shown]
        ui.aggrid(
            {
                "columnDefs": [
                    {"field": "old", "headerName": "ID in the file", "flex": 1},
                    {
                        "field": "new",
                        "headerName": "Corrected ID",
                        "editable": True,
                        "flex": 1,
                        "cellClassRules": {"lc-bad-text": "data.clash"},
                    },
                    {"field": "matches", "headerName": "Matches the ID pattern", "width": 170},
                    {"field": "listed", "headerName": "In the roster", "width": 120},
                    {"field": "note", "headerName": "Note", "flex": 1},
                ],
                "rowData": [
                    {
                        "old": r.old,
                        "new": r.new,
                        "matches": mark(r.matches),
                        "listed": mark(r.listed),
                        "clash": r.clash,
                        "note": "the same as another ID" if r.clash else "",
                    }
                    for r in shown
                ],
                "stopEditingWhenCellsLoseFocus": True,
            }
        ).classes("w-full h-80").on("cellValueChanged", typed)
        save_button.set_enabled(bool(changed or saved_here()) and not clashes)

    def saved_here() -> bool:
        return bool(id_map.mapping(root, state.dataset))

    def confirm() -> None:
        found = rows()
        changed = [r for r in found if r.new != r.old]
        loaded = result.datasets[state.dataset]
        source = loaded.source_path.name if loaded.source_path else state.dataset

        async def go() -> None:
            id_map.save(root, state.dataset, found)
            asked.close()
            dialog.close()
            await on_saved()

        with ui.dialog() as asked, ui.card().classes("w-[30rem] max-w-full gap-3"):
            ui.label(f"Correct {len(changed)} IDs in {state.dataset}?").classes("font-medium")
            ui.label(
                f"labcatalog writes them to {defaults.ID_MAP_FILENAME} in the project folder and "
                f"uses them whenever it reads {source}; the data file itself stays as it is. "
                "Deleting a line of that file undoes its correction."
            )
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=asked.close).props("flat")
                ui.button("Correct the IDs", icon="check", on_click=go)
        asked.open()

    def show(value: str) -> None:
        state.shown = value
        preview.refresh()

    with ui.dialog() as dialog, ui.card().classes("w-[60rem] max-w-full gap-3"):
        ui.label("Fix IDs").classes("lc-panel-title")
        note(
            "Rules turn the IDs as the file writes them into the project's IDs, in order; type "
            "an ID in the Corrected ID column to set it by hand. Nothing changes until you press "
            "Save and confirm, and the data file is never changed."
        )
        with ui.row().classes("w-full items-center gap-4"):
            ui.select(
                names,
                value=state.dataset,
                label="Dataset",
                on_change=lambda e: choose_dataset(e.value),
            ).classes("w-64")
            if pattern()[0]:
                note(f"{pattern()[1]}: {pattern()[0]}")
            ui.space()
            ui.toggle(SHOWN, value=state.shown, on_change=lambda e: show(e.value)).props(
                "dense no-caps"
            )
        rules_view()
        with ui.row().classes("w-full justify-end gap-2 order-last"):
            ui.button("Close", on_click=dialog.close).props("flat")
            save_button = ui.button("Save", icon="save", on_click=confirm)
        preview()
    dialog.open()


def mark(value: bool | None) -> str:
    return "" if value is None else YES if value else NO
