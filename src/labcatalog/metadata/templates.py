from ruamel.yaml.comments import CommentedMap

from labcatalog import defaults
from labcatalog.codebook.core import MODELINE
from labcatalog.metadata import editing, records
from labcatalog.metadata.changes import Change
from labcatalog.metadata.studies import place_key, set_block, study_file
from labcatalog.project import Project
from labcatalog.reports import templates
from labcatalog.schema import Instrument


def template_change(
    project: Project, key: str, texts: dict[str, str], owner: str | None = None
) -> Change:
    # A text equal to the one it would fall back to is left out of the file.
    found = templates.TEMPLATES[key]
    if owner is None:
        return project_change(project, found, texts)
    text = texts[templates.PARAGRAPH]
    if same(text, templates.project_text(project.config, key)):
        text = ""
    if found.own == templates.STUDY:
        return study_change(project, owner, text)
    return instrument_change(project, owner, text)


def project_change(project: Project, found: templates.Template, texts: dict[str, str]) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    held = data.get("templates") or CommentedMap()
    kept = {k: t for k, t in texts.items() if not same(t, found.slot(k).default)}
    if found.single:
        set_block(held, found.key, kept.get(templates.PARAGRAPH, ""))
    else:
        parts = held.get(found.key) or CommentedMap()
        for slot in found.slots:
            set_block(parts, slot.key, kept.get(slot.key, ""))
        if parts:
            held[found.key] = parts
        else:
            held.pop(found.key, None)
    if held:
        place_key(data, "templates", held, after=list(data)[-1])
    else:
        data.pop("templates", None)
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def study_change(project: Project, study: str, text: str) -> Change:
    relative = study_file(project, study)
    opened = None
    source = f"{MODELINE.format('study')}\nstudy: {study}\n"
    if (project.root / relative).exists():
        opened = editing.open_file(project.root, relative)
        source = opened.text
    data = records.load(source)
    set_block(data, "participants", text, after="methods" if "methods" in data else "study")
    return Change(relative, records.dumped(data), opened)


def instrument_change(project: Project, instrument_id: str, text: str) -> Change:
    relative = project.instrument_files[instrument_id]
    opened = editing.open_file(project.root, relative)
    data = records.load(opened.text)
    order = list(Instrument.model_fields)
    before = [k for k in order[: order.index("measures")] if k in data]
    set_block(data, "measures", text, after=before[-1])
    return Change(relative, records.dumped(data), opened)


def same(text: str, other: str) -> bool:
    return " ".join(text.split()) == " ".join(other.split())
