import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed, page_head, panel
from labcatalog.metadata import changes
from labcatalog.metadata.templates import same, template_change
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import measures, participants, template_examples, templates
from labcatalog.reports.templates import INSTRUMENT, PARAGRAPH, STUDY, Template, Wording

# The owner choice that stands for the project's own wording.
PROJECT = ""


@dataclass
class TemplatesView:
    key: str = "participants"
    owner: str = PROJECT
    edited: bool = False


def render(
    result: CatalogResult, view: TemplatesView, on_saved: Callable[[], Awaitable[None]]
) -> None:
    if view.key not in templates.TEMPLATES:
        view.key = next(iter(templates.TEMPLATES))

    def leave(then: Callable[[], None]) -> None:
        if not view.edited:
            then()
            return
        with frame, ui.dialog() as dialog, ui.card():
            ui.label(f"Discard your changes to {templates.TEMPLATES[view.key].title}?")
            with ui.row():
                ui.button("Discard", on_click=lambda: (dialog.close(), then()))
                ui.button("Keep editing", on_click=dialog.close).props("flat")
        dialog.open()

    def go(key: str, owner: str) -> None:
        view.key, view.owner, view.edited = key, owner, False
        page.refresh()

    def choose(key: str) -> None:
        if key != view.key:
            leave(partial(go, key, PROJECT))

    @ui.refreshable
    def page() -> None:
        found = templates.TEMPLATES[view.key]
        if view.owner not in owners(result, found):
            view.owner = PROJECT
        with ui.row().classes("w-full no-wrap items-start gap-6"):
            with ui.column().classes("w-64 shrink-0 lc-side"):
                for part in (templates.METHODS, templates.RESULTS):
                    listed = [t for t in templates.TEMPLATES.values() if t.part == part]
                    if not listed:
                        continue
                    with panel(part), ui.column().classes("w-full gap-0"):
                        for t in listed:
                            item = (
                                ui.item(t.title, on_click=partial(choose, t.key))
                                .props("dense clickable")
                                .classes("lc-pick")
                            )
                            if t.key == view.key:
                                item.classes("lc-info font-medium")
            with ui.column().classes("grow min-w-0 gap-4"):
                editor(result, view, found, leave, go, on_saved)

    with ui.column().classes("w-full gap-4") as frame:
        page_head(
            "Templates",
            help_text="The wording of the paragraphs labcatalog writes; the numbers fill in.",
        )
        page()


def editor(
    result: CatalogResult,
    view: TemplatesView,
    found: Template,
    leave: Callable[[Callable[[], None]], None],
    go: Callable[[str, str], None],
    on_saved: Callable[[], Awaitable[None]],
) -> None:
    project = result.project
    current = wording(result, found, view.owner)
    written = methods_text(result, found, view.owner, Wording({found.key: current}))
    filled = written[1] if written else None
    boxes: dict[str, ui.textarea] = {}
    shown: dict[str, ui.label] = {}

    def touched() -> None:
        view.edited = True
        save_button.enable()
        preview()

    def preview() -> None:
        texts = {k: box.value or "" for k, box in boxes.items()}
        problems = {
            k: problem
            for k, text in texts.items()
            if (problem := templates.placeholder_problem(text, found.slot(k).placeholders))
        }
        for key, label in shown.items():
            slot = found.slot(key)
            text = texts[key] or slot.default
            label.set_text(problems.get(key) or f"Example: {flat(text.format_map(slot.example))}")
            label.classes(replace="text-negative" if key in problems else "lc-note")
        whole.classes(replace="text-negative" if problems else "lc-prose")
        if problems:
            whole.set_text("; ".join(f"{found.slot(k).label}: {p}" for k, p in problems.items()))
        elif filled is not None:
            whole.set_text(methods_text(result, found, view.owner, Wording({found.key: texts}))[0])
        else:
            whole.set_text(template_examples.EXAMPLES[found.key](Wording({found.key: texts})))

    def reset() -> None:
        for key, box in boxes.items():
            box.set_value(fallback(result, found, view.owner)[key])

    async def save() -> None:
        texts = {k: box.value or "" for k, box in boxes.items()}
        try:
            change = template_change(project, found.key, texts, view.owner or None)
            pending = [change] if change.opened is None or change.text != change.opened.text else []
            issues = await computed(changes.check, project, pending)
            if issues:
                refused.set_text("; ".join(i.message for i in issues))
                ui.notify("Not saved: fix the problems listed above", type="warning")
                return
            changes.write(project, pending)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        view.edited = False
        ui.notify(f"Saved {found.title}")
        await on_saved()

    with ui.row().classes("w-full no-wrap items-start gap-4"):
        with ui.column().classes("grow min-w-0 gap-4"), panel(found.title, help_text=found.help):
            choices = owners(result, found)
            if len(choices) > 1:
                ui.select(
                    choices,
                    value=view.owner,
                    label="For",
                    on_change=lambda e: leave(partial(go, found.key, e.value)),
                ).props("dense outlined options-dense").classes("w-72")
            ui.label(source(result, found, view.owner)).classes("lc-note")
            for slot in found.slots:
                box = (
                    ui.textarea(
                        slot.label,
                        value=current[slot.key],
                        on_change=touched,
                    )
                    .props("outlined")
                    .classes("lc-grow w-full")
                )
                boxes[slot.key] = box
                # The paragraph's placeholders hold whole sentences of the project's data.
                stand_ins = filled if filled is not None and slot.key == PARAGRAPH else slot.example
                with ui.row().classes("gap-1 items-center"):
                    for name in slot.placeholders:
                        ui.chip(f"{{{name}}}", on_click=partial(insert, box, f"{{{name}}}")).props(
                            "dense clickable outline"
                        ).classes("font-mono").tooltip(stand_ins.get(name) or "Empty here")
                if filled is None or slot.key != PARAGRAPH:
                    shown[slot.key] = ui.label()
            refused = ui.label().classes("text-negative")
            with ui.row().classes("lc-actions w-full"):
                save_button = ui.button("Save", icon="save", on_click=save).props("no-caps")
                save_button.disable()
                ui.button("Reset", icon="restart_alt", on_click=reset).props(
                    "flat no-caps"
                ).tooltip("Back to the wording this falls back to; Save to keep it")
        with (
            ui.column().classes("w-96 shrink-0 lc-sticky"),
            panel("Paragraph", help_text=paragraph_help(found)),
        ):
            whole = ui.label().classes("lc-prose")
    preview()


def insert(box: ui.textarea, text: str) -> None:
    # At the cursor, as typing would, so the box's own change event follows.
    ui.run_javascript(
        f"const el = getHtmlElement({box.id}).querySelector('textarea');"
        f"el.setRangeText({json.dumps(text)}, el.selectionStart, el.selectionEnd, 'end');"
        "el.dispatchEvent(new Event('input', {bubbles: true})); el.focus();"
    )


def owners(result: CatalogResult, found: Template) -> dict[str, str]:
    project = result.project
    choices = {PROJECT: "The project"}
    if found.own == STUDY:
        choices |= {s: c.label or s for s, c in project.config.studies.items()}
    if found.own == INSTRUMENT:
        choices |= {i: f"{x.abbreviation or i}: {x.name}" for i, x in project.instruments.items()}
    return choices


def wording(result: CatalogResult, found: Template, owner: str) -> dict[str, str]:
    project = result.project
    own = None
    if owner and found.own == STUDY:
        own = next((c.participants for c in project.studies.values() if c.study == owner), None)
    elif owner and found.own == INSTRUMENT:
        own = project.instruments[owner].measures
    written = templates.layered(project.config, found.key, own)
    return {s.key: written.text(found.key, s.key) for s in found.slots}


def fallback(result: CatalogResult, found: Template, owner: str) -> dict[str, str]:
    if owner == PROJECT:
        return {s.key: s.default for s in found.slots}
    return {
        s.key: templates.project_text(result.project.config, found.key, s.key) for s in found.slots
    }


def source(result: CatalogResult, found: Template, owner: str) -> str:
    now, back = wording(result, found, owner), fallback(result, found, owner)
    if all(same(now[k], back[k]) for k in now):
        return "The built-in wording." if owner == PROJECT else "The project's wording."
    return "The project's own wording." if owner == PROJECT else "Its own wording."


def methods_subject(result: CatalogResult, found: Template, owner: str):
    # The study, or the instrument and a dataset that gives it, a Methods template is written for.
    project = result.project
    if found.key == "participants":
        return owner or next(iter(project.config.studies), None)
    given = [(v.instrument_id, v.dataset) for v in result.catalog.variables]
    pairs = [p for p in given if p[0] == owner] if owner else given
    return pairs[0] if pairs else None


def methods_text(result: CatalogResult, found: Template, owner: str, written: Wording):
    # The paragraph and what each of its placeholders holds; None for a Results template.
    if found.part != templates.METHODS:
        return None
    project = result.project
    subject = methods_subject(result, found, owner)
    if subject is None:
        return no_data(found), {}
    if found.key == "participants":
        values = participants.placeholder_values(project, result.summary, subject, written)
    else:
        instrument, dataset = project.instruments[subject[0]], subject[1]
        values = measures.placeholder_values(
            project, result.catalog, result.summary, instrument, dataset, [], written
        )
    return written.say(found.key, PARAGRAPH, **values), values


def no_data(found: Template) -> str:
    return "No study yet." if found.key == "participants" else "Not given in any dataset yet."


def flat(text: str) -> str:
    return " ".join(text.split())


def paragraph_help(found: Template) -> str:
    if found.part == templates.METHODS:
        return "From the project's data, before ω from the factor models."
    return "A made-up result, written with the wording on the left."
