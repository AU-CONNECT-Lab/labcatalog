from collections.abc import Callable
from dataclasses import dataclass

from nicegui import ui

from labcatalog.codebook.core import unmapped_datasets
from labcatalog.data.prepare import step_states
from labcatalog.gui import codebook_step, id_check
from labcatalog.pipeline import CatalogResult

CODEBOOK, DATA, IDS, REVIEW = "codebook", "data", "ids", "review"
STEPS = {
    CODEBOOK: "Codebook",
    DATA: "Add data",
    IDS: "Check IDs",
    REVIEW: "Review",
}
# Where the last step's Next button leads.
AFTER = ("problems", "Problems")


@dataclass
class SetupView:
    step: str = CODEBOOK


def counts(result: CatalogResult | None) -> dict[str, dict[str, int]]:
    # What each step still has to do, by kind; a kind with nothing left is left out.
    project = result.project if result else None
    if project is None:
        return {}
    found = {
        CODEBOOK: {"drafts": len(codebook_step.drafts(project.root))},
        DATA: {
            "to run": sum(s.status != "up to date" for s in step_states(project)),
            "to link": len(unmapped_datasets(project)),
        },
        IDS: {"to check": id_check.waiting(result)},
    }
    return {step: {kind: n for kind, n in kinds.items() if n} for step, kinds in found.items()}


def to_do(result: CatalogResult | None) -> dict[str, str]:
    return {
        step: " · ".join(f"{n} {kind}" for kind, n in kinds.items())
        for step, kinds in counts(result).items()
    }


def next_button(step: str, on_pick: Callable[[str], None]) -> None:
    names = list(STEPS)
    following = names.index(step) + 1
    target, label = (names[following], STEPS[names[following]]) if following < len(names) else AFTER
    with ui.row().classes("w-full justify-end"):
        ui.button(f"Next: {label}", on_click=lambda: on_pick(target)).props(
            "flat no-caps icon-right=arrow_forward"
        ).classes("lc-quiet-btn")
