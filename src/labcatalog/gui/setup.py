from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

from labcatalog.codebook.core import unmapped_datasets
from labcatalog.data.prepare import step_states
from labcatalog.gui import codebook_step, id_check
from labcatalog.pipeline import CatalogResult

CODEBOOK, DATA, IDS, EDIT, REVIEW = "codebook", "data", "ids", "edit", "review"
STEPS = {
    CODEBOOK: "Codebook",
    DATA: "Add data",
    IDS: "Check IDs",
    EDIT: "Edit files",
    REVIEW: "Review",
}
# Where the last step's Next button leads.
AFTER = ("problems", "Problems")


@dataclass
class SetupView:
    step: str = CODEBOOK


def to_do(result: CatalogResult | None) -> dict[str, str]:
    project = result.project if result else None
    if project is None:
        return {}
    waiting = sum(s.status != "up to date" for s in step_states(project))
    unmapped = len(unmapped_datasets(project))
    checking = id_check.waiting(result)
    drafted = len(codebook_step.drafts(project.root))
    data = [f"{waiting} to run" if waiting else "", f"{unmapped} to link" if unmapped else ""]
    return {
        CODEBOOK: f"{drafted} drafts" if drafted else "",
        DATA: " · ".join(filter(None, data)),
        IDS: f"{checking} to check" if checking else "",
    }


def step_bar(view: SetupView, counts: dict[str, str], on_pick: Callable[[str], None]) -> ui.tabs:
    with (
        ui.tabs(value=view.step, on_change=lambda e: on_pick(e.value))
        .props("dense no-caps inline-label align=left")
        .classes("lc-subnav lc-steps w-full") as tabs
    ):
        for number, (name, label) in enumerate(STEPS.items(), start=1):
            if number > 1:
                ui.icon("chevron_right").classes("lc-step-arrow")
            with ui.tab(name, label=""):
                ui.label(str(number)).classes("lc-step-num")
                ui.label(label).classes("q-tab__label")
                if counts.get(name):
                    ui.label(counts[name]).classes("lc-pill lc-warn ml-2")
    return tabs


def next_button(step: str, on_pick: Callable[[str], None]) -> None:
    names = list(STEPS)
    following = names.index(step) + 1
    target, label = (names[following], STEPS[names[following]]) if following < len(names) else AFTER
    with ui.row().classes("w-full justify-end"):
        ui.button(f"Next: {label}", on_click=lambda: on_pick(target)).props(
            "flat no-caps icon-right=arrow_forward"
        ).classes("lc-quiet-btn")
