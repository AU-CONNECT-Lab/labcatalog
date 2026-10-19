from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui

from labcatalog.metadata.browse import Facet


@dataclass
class Filters:
    selected: dict[str, set[str]] = field(default_factory=dict)
    query: str = ""

    def any(self) -> bool:
        return bool(self.query or any(self.selected.values()))


def filter_bar(
    facets: list[Facet],
    count: Callable[[], dict[str, dict[str, int]]],
    filters: Filters,
    changed: Callable[[], None],
) -> None:
    # A facet with one value cannot narrow anything.
    shown = [f for f in facets if len(f.values) > 1 or filters.selected.get(f.name)]
    buttons: dict[str, ui.button] = {}
    menus: dict[str, ui.refreshable] = {}

    def update() -> None:
        found = count()
        for facet in shown:
            buttons[facet.name].set_text(title(facet))
            buttons[facet.name].classes(
                **{"add" if filters.selected.get(facet.name) else "remove": "lc-active"}
            )
            menus[facet.name].refresh(found)
        chips.refresh()
        clear.set_visibility(filters.any())
        changed()

    def toggle(name: str, value: str, on: bool) -> None:
        chosen = filters.selected.setdefault(name, set())
        if on:
            chosen.add(value)
        else:
            chosen.discard(value)
        update()

    def set_query(value: str | None) -> None:
        filters.query = value or ""
        update()

    def clear_all() -> None:
        filters.selected.clear()
        box.set_value("")
        update()

    def title(facet: Facet) -> str:
        n = len(filters.selected.get(facet.name, ()))
        return f"{facet.label} · {n}" if n else facet.label

    def menu_body(facet: Facet, found: dict[str, dict[str, int]]) -> None:
        chosen = filters.selected.get(facet.name, set())
        for value, label in facet.values.items():
            n = found[facet.name][value]
            if n or value in chosen:
                check = ui.checkbox(
                    f"{label} ({n})",
                    value=value in chosen,
                    on_change=lambda e, v=value: toggle(facet.name, v, e.value),
                ).props("dense")
                if value in facet.parents:
                    check.classes("q-ml-md")

    @ui.refreshable
    def chips() -> None:
        def remove(name: str, value: str) -> None:
            filters.selected[name].discard(value)
            update()

        picked = [
            (facet, value)
            for facet in facets
            for value in facet.values
            if value in filters.selected.get(facet.name, set())
        ]
        if not picked:
            return
        with ui.row().classes("gap-1 items-center"):
            for facet, value in picked:
                ui.chip(
                    f"{facet.label}: {facet.values[value]}",
                    removable=True,
                    color=None,
                    on_value_change=lambda _, n=facet.name, v=value: remove(n, v),
                ).props("dense").classes("lc-filter-chip")

    # Only the menus and chips are drawn again on a change, so an open menu stays open.
    found = count()
    with ui.row().classes("w-full items-center gap-2"):
        box = (
            ui.input(
                placeholder="Search", value=filters.query, on_change=lambda e: set_query(e.value)
            )
            .props("dense outlined clearable")
            .classes("w-72")
        )
        for facet in shown:
            with (
                ui.button(title(facet))
                .props("flat no-caps icon-right=expand_more")
                .classes("lc-quiet-btn") as buttons[facet.name]
            ):
                with ui.menu(), ui.column().classes("gap-0 p-3"):
                    menus[facet.name] = ui.refreshable(lambda found, f=facet: menu_body(f, found))
                    menus[facet.name](found)
            if filters.selected.get(facet.name):
                buttons[facet.name].classes("lc-active")
        clear = ui.button("Clear", on_click=clear_all).props("flat dense no-caps")
        clear.set_visibility(filters.any())
    chips()
