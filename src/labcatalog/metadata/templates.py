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
    # A part equal to the one it would fall back to is left out of the file.
    found = templates.TEMPLATES[key]
    if owner is None:
        back = {s.key: s.default for s in found.slots}
    else:
        back = {s.key: templates.project_text(project.config, key, s.key) for s in found.slots}
    kept = {k: t for k, t in texts.items() if not same(t, back[k])}
    if owner is None:
        return project_change(project, found, kept)
    if found.own == templates.STUDY:
        return study_change(project, owner, found, kept)
    return instrument_change(project, owner, found, kept)


def project_change(project: Project, found: templates.Template, kept: dict[str, str]) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    held = data.get("templates") or CommentedMap()
    put_parts(held, found, kept, None)
    if held:
        place_key(data, "templates", held, after=list(data)[-1])
    else:
        data.pop("templates", None)
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def study_change(
    project: Project, study: str, found: templates.Template, kept: dict[str, str]
) -> Change:
    relative = study_file(project, study)
    opened = None
    source = f"{MODELINE.format('study')}\nstudy: {study}\n"
    if (project.root / relative).exists():
        opened = editing.open_file(project.root, relative)
        source = opened.text
    data = records.load(source)
    put_parts(data, found, kept, "methods" if "methods" in data else "study")
    return Change(relative, records.dumped(data), opened)


def instrument_change(
    project: Project, instrument_id: str, found: templates.Template, kept: dict[str, str]
) -> Change:
    relative = project.instrument_files[instrument_id]
    opened = editing.open_file(project.root, relative)
    data = records.load(opened.text)
    order = list(Instrument.model_fields)
    before = [k for k in order[: order.index("measures")] if k in data]
    put_parts(data, found, kept, before[-1])
    return Change(relative, records.dumped(data), opened)


def put_parts(
    parent: CommentedMap, found: templates.Template, kept: dict[str, str], after: str | None
) -> None:
    # Each part as a block under the template's key; one text written by hand was its paragraph.
    held = parent.get(found.key)
    parts = held if isinstance(held, dict) else CommentedMap()
    if isinstance(held, str):
        parts[templates.PARAGRAPH] = held
    for slot in found.slots:
        set_block(parts, slot.key, kept.get(slot.key, ""))
    if not parts:
        parent.pop(found.key, None)
    elif after is None:
        parent[found.key] = parts
    else:
        place_key(parent, found.key, parts, after)


def same(text: str, other: str) -> bool:
    return " ".join(text.split()) == " ".join(other.split())
