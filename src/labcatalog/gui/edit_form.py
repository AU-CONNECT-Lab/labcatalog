from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from nicegui import ui

from labcatalog.exceptions import EditError
from labcatalog.gui.common import note, panel
from labcatalog.metadata import forms, records
from labcatalog.metadata.records import Column

# Text that runs to sentences gets a box that grows with it.
LONG = {"text", "description", "instructions"}


@dataclass
class Form:
    sections: list[forms.Section]
    rows: dict[str, list[dict]]
    # The rows as read, so a section left alone is not written back.
    read: dict[str, list[dict]]
    # Sections the form cannot show, with the reason.
    broken: dict[str, str]
    edited: bool = False

    def text(self, text: str) -> str:
        for section in self.sections:
            rows = self.rows.get(section.key)
            if rows is not None and rows != self.read[section.key]:
                text = records.write_rows(text, section.key, section.table, rows)
        return text


def open_form(root: Path, relative: str, text: str) -> Form:
    found = forms.sections(root, relative, text)
    rows, broken = {}, {}
    for section in found:
        try:
            rows[section.key] = records.read_rows(text, section.key, section.table)
        except EditError as err:
            broken[section.key] = str(err)
    return Form(found, rows, deepcopy(rows), broken)


def render(form: Form) -> None:
    def touch() -> None:
        form.edited = True

    @ui.refreshable
    def everything() -> None:
        for section in form.sections:
            if section.key in form.broken:
                with panel(section.table.label):
                    note(f"{form.broken[section.key]} (Advanced, then Text).")
            elif section.table.single:
                fields_section(form.rows[section.key][0], section, touch)
            elif section.table.inner and not section.table.parent:
                groups_section(form, section, touch, everything.refresh)
            else:
                list_section(form.rows[section.key], section, touch)

    everything()


def fields_section(row: dict, section: forms.Section, touch: Callable[[], None]) -> None:
    with panel(section.table.label), ui.element("div").classes("lc-form w-full"):
        for column in section.table.columns:
            shown = widget(row, column, section, touch)
            if column.key in LONG:
                shown.classes("lc-form-wide")


def list_section(rows: list[dict], section: forms.Section, touch: Callable[[], None]) -> None:
    columns = section.table.columns
    primary = [c for c in columns if c.key in section.primary] or list(columns[:3])
    rest = [c for c in columns if c not in primary]

    def changed() -> None:
        touch()
        body.refresh()

    # A column other columns take their choices from redraws the entries when it changes.
    drivers = {driver for driver, _ in section.follows.values()}

    def changed_by(column: Column) -> Callable[[], None]:
        return changed if column.key in drivers else touch

    def add() -> None:
        new = {c.key: records.shown(None, c) for c in columns}
        first = columns[0]
        if first.choices:
            new[first.key] = first.choices[0]
        elif first.key in ("id", "name"):
            taken = [str(r[first.key]) for r in rows]
            new[first.key] = forms.next_id(taken, section.noun.replace(" ", "_"))
        if rows:
            new |= {key: rows[-1][key] for key in section.carried}
        rows.append(new)
        changed()

    def move(n: int, step: int) -> None:
        rows[n], rows[n + step] = rows[n + step], rows[n]
        changed()

    def remove(n: int) -> None:
        del rows[n]
        changed()

    @ui.refreshable
    def body() -> None:
        if not rows:
            note(f"No {section.noun}s yet.")
        for n, row in enumerate(rows):
            with ui.column().classes("lc-form-entry w-full gap-1"):
                with ui.row().classes("w-full items-start gap-2 no-wrap"):
                    ui.label(str(n + 1)).classes("lc-form-number")
                    for column in primary:
                        widget(row, column, section, changed_by(column)).classes(
                            width(column, section)
                        )
                    with ui.row().classes("shrink-0 gap-0 no-wrap"):
                        if rest:
                            more = icon_button("tune", "More fields")
                        icon_button("arrow_upward", "Move up", partial(move, n, -1), n > 0)
                        icon_button(
                            "arrow_downward", "Move down", partial(move, n, 1), n < len(rows) - 1
                        )
                        icon_button("delete_outline", "Delete", partial(remove, n))
                if rest:
                    details = ui.element("div").classes("lc-form lc-form-details w-full")
                    with details:
                        for column in rest:
                            widget(row, column, section, changed_by(column))
                    details.set_visibility(False)
                    more.on_click(lambda d=details: d.set_visibility(not d.visible))

    with panel(section.table.label, help_text=section.help) as tools:
        with tools:
            ui.button(f"Add {section.noun}", icon="add", on_click=add).props("flat dense no-caps")
        body()


def groups_section(
    form: Form, section: forms.Section, touch: Callable[[], None], redraw: Callable[[], None]
) -> None:
    # Rows sharing the first column make one entry: the options of one response set.
    rows = form.rows[section.key]
    group, *columns = section.table.columns

    def changed() -> None:
        touch()
        body.refresh()

    def blank(name: str, value: str) -> dict:
        new = {c.key: records.shown(None, c) for c in columns}
        return new | {group.key: name, columns[0].key: value}

    def add_group() -> None:
        names = list(dict.fromkeys(r[group.key] for r in rows))
        rows.append(blank(forms.next_id(names, "set"), "1"))
        changed()

    def add_member(name: str) -> None:
        last = max(n for n, r in enumerate(rows) if r[group.key] == name)
        value = str(rows[last][columns[0].key])
        rows.insert(last + 1, blank(name, str(int(value) + 1) if value.isdigit() else ""))
        changed()

    def rename(box: ui.input, old: str) -> None:
        new = str(box.value).strip()
        names = {r[group.key] for r in rows}
        # Enter then blur sends a second rename after the first already went through.
        if new == old or old not in names:
            return
        if not new or new in names:
            ui.notify(
                f"Another {section.noun} is already called {new}."
                if new
                else f"A {section.noun} needs an ID.",
                type="warning",
            )
            box.value = old
            return
        form.sections = forms.rename_set(form.sections, form.rows, old, new)
        touch()
        redraw()

    def remove(members: list[dict]) -> None:
        rows[:] = [r for r in rows if not any(r is m for m in members)]
        changed()

    @ui.refreshable
    def body() -> None:
        if not rows:
            note(f"No {section.noun}s yet.")
        for name in dict.fromkeys(r[group.key] for r in rows):
            members = [r for r in rows if r[group.key] == name]
            with ui.column().classes("lc-form-entry w-full gap-1"):
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    # Renamed when the box is left, so typing does not rename at each key.
                    box = ui.input(group.label, value=name).props("dense outlined").classes("w-48")
                    for event in ("blur", "keydown.enter"):
                        box.on(event, lambda b=box, n=name: rename(b, n))
                    ui.space()
                    icon_button(
                        "delete_outline", f"Delete this {section.noun}", partial(remove, members)
                    )
                for member in members:
                    with ui.row().classes("w-full items-start gap-2 no-wrap pl-4"):
                        for column in columns:
                            widget(member, column, section, touch).classes(width(column, section))
                        icon_button("close", "Delete", partial(remove, [member]))
                ui.button("Add option", icon="add", on_click=partial(add_member, name)).props(
                    "flat dense no-caps"
                ).classes("ml-2")

    with panel(section.table.label) as tools:
        with tools:
            ui.button(f"Add {section.noun}", icon="add", on_click=add_group).props(
                "flat dense no-caps"
            )
        body()


def widget(row: dict, column: Column, section: forms.Section, touch: Callable[[], None]):
    key = column.key

    def set_value(value) -> None:
        row[key] = value
        touch()

    value = row[key]
    if column.kind == "bool":
        return ui.checkbox(
            column.label, value=bool(value), on_change=lambda e: set_value(e.value)
        ).props("dense")
    if column.kind == "number":
        return ui.number(
            column.label,
            value=None if value == "" else value,
            on_change=lambda e: set_value("" if e.value is None else e.value),
        ).props("dense outlined")
    options = list(dict.fromkeys(section.options_for(row, key) or column.choices))
    if column.kind == "list":
        chosen = [part.strip() for part in str(value).split(",") if part.strip()]
        return ui.select(
            list(dict.fromkeys([*options, *chosen])),
            label=column.label,
            value=chosen,
            multiple=True,
            with_input=True,
            new_value_mode="add-unique",
            on_change=lambda e: set_value(", ".join(e.value or [])),
        ).props("dense outlined use-chips")
    if options:
        if value not in options:
            options.append(value)
        # A lab's own field takes new values too; saving then adds them to its choices.
        fixed = column.kind == "choice" and not key.startswith(records.CUSTOM + records.NESTED)
        return ui.select(
            options,
            label=column.label,
            value=value,
            with_input=not fixed,
            new_value_mode=None if fixed else "add-unique",
            on_change=lambda e: set_value("" if e.value is None else e.value),
        ).props("dense outlined")
    if key in LONG:
        shown = (
            ui.textarea(column.label, value=str(value), on_change=lambda e: set_value(e.value))
            .props("dense outlined")
            .classes("lc-grow")
        )
    else:
        shown = ui.input(
            column.label, value=str(value), on_change=lambda e: set_value(e.value)
        ).props("dense outlined")
    if key in section.fixed:
        shown.props("readonly")
    return shown


def width(column: Column, section: forms.Section) -> str:
    # Single values get fixed widths so the entries line up; lists and text take the rest.
    if column.kind == "bool":
        return "shrink-0 pt-2"
    if column.key in ("id", "name", "value", "study", "wave"):
        return "w-40 shrink-0"
    if column.kind in ("choice", "number") or (
        column.kind != "list" and column.key in section.options
    ):
        return "w-48 shrink-0"
    return "grow min-w-0"


def icon_button(icon: str, tip: str, action: Callable | None = None, enabled: bool = True):
    shown = ui.button(icon=icon, on_click=action).props("flat dense round size=sm")
    shown.tooltip(tip)
    shown.set_enabled(enabled)
    return shown
