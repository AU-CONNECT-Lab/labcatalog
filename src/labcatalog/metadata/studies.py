from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import LiteralScalarString

from labcatalog import defaults
from labcatalog.codebook.core import MODELINE
from labcatalog.config import StudyConfig, WaveConfig
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing, records
from labcatalog.metadata.changes import Change
from labcatalog.project import Project

FIELDS = (
    records.Column("label", "Label"),
    records.Column("description", "Description"),
    records.Column("reference", "Reference"),
)
WAVE = records.Column("wave", "Wave")
DATES = (records.Column("start", "Start", "date"), records.Column("end", "End", "date"))
MILESTONES = (records.Column("name", "Name"), records.Column("date", "Date", "date"))


@dataclass
class Edited:
    fields: dict[str, str]
    # Each row keeps under ORIGIN the wave's key, or the milestone's place, it was read from.
    waves: list[dict]
    milestones: list[dict]


def wave_rows(study: StudyConfig) -> list[dict]:
    return [
        {records.ORIGIN: wave, WAVE.key: wave}
        | {c.key: records.shown(getattr(dates, c.key), c) for c in DATES}
        for wave, dates in study.waves.items()
    ]


def milestone_rows(study: StudyConfig) -> list[dict]:
    return [
        {records.ORIGIN: n} | {c.key: records.shown(getattr(m, c.key), c) for c in MILESTONES}
        for n, m in enumerate(study.milestones)
    ]


def wave_status(wave: WaveConfig, today: date) -> str:
    if wave.start is None:
        return ""
    if wave.start > today:
        return "Planned"
    return "Finished" if wave.end and wave.end < today else "Collecting"


def edit_change(project: Project, study: str, edited: Edited) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    entry = data["studies"][study]
    # Whatever follows the study, such as the next section's comment, stays after it.
    tail = records.take_tail(entry)
    records.fill(entry, FIELDS, edited.fields)
    write_waves(entry, edited.waves)
    write_milestones(entry, edited.milestones)
    records.put_tail(entry, tail)
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def write_waves(entry: CommentedMap, rows: list[dict]) -> None:
    old = entry.get("waves") or CommentedMap()
    by_name = {str(key): key for key in old}
    # A project whose waves are numbers gets numbers for new waves too.
    numeric = all(isinstance(key, int) for key in old)
    names = []
    for row in rows:
        name = records.stored(row.get(WAVE.key), WAVE)
        if name is None:
            raise EditError("Wave: every row needs one")
        if name in names:
            raise EditError(f"Wave {name} is listed twice")
        names.append(name)
    origins = [row.get(records.ORIGIN) for row in rows]
    if names == origins == list(by_name):
        waves = old
    else:
        waves = CommentedMap()
        for name, origin in zip(names, origins, strict=True):
            key = int(name) if numeric and name.isdigit() else records.as_text(name)
            if origin in by_name:
                waves[key] = old[by_name[origin]]
                # A comment on a wave's line moves with the wave.
                if by_name[origin] in old.ca.items:
                    waves.ca.items[key] = old.ca.items[by_name[origin]]
            else:
                waves[key] = CommentedMap()
                waves[key].fa.set_flow_style()
    for value, row in zip(waves.values(), rows, strict=True):
        records.fill(value, DATES, row)
    if waves:
        entry["waves"] = waves
    else:
        entry.pop("waves", None)


def write_milestones(entry: CommentedMap, rows: list[dict]) -> None:
    if not rows:
        entry.pop("milestones", None)
        return
    origins = [row.get(records.ORIGIN) for row in rows]
    for row, milestone in zip(rows, records.place(entry, "milestones", origins), strict=True):
        records.fill(milestone, MILESTONES, row)


def text_change(
    project: Project, study: str, methods: dict[str, str], participants: str
) -> Change | None:
    relative = study_file(project, study)
    opened = None
    text = f"{MODELINE.format('study')}\nstudy: {study}\n"
    if (project.root / relative).exists():
        opened = editing.open_file(project.root, relative)
        text = opened.text
    data = records.load(text)
    written = data.get("methods") or CommentedMap()
    for modality, paragraphs in methods.items():
        set_block(written, modality, paragraphs)
    if written:
        place_key(data, "methods", written, after="study")
    else:
        data.pop("methods", None)
    set_block(data, "participants", participants, after="methods" if written else "study")
    new = records.dumped(data)
    return None if new == text else Change(relative, new, opened)


def study_file(project: Project, study: str) -> str:
    return project.study_files.get(study, f"{defaults.STUDIES_DIR}/{study}.yaml")


def set_block(parent: CommentedMap, key: str, text: str, after: str | None = None) -> None:
    # One line per paragraph and a blank line between them, written as a | block.
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").strip().split("\n")]
    clean = "\n".join(lines)
    if clean == str(parent.get(key) or "").strip():
        return
    if not clean:
        parent.pop(key, None)
    elif after is None:
        parent[key] = LiteralScalarString(clean + "\n")
    else:
        place_key(parent, key, LiteralScalarString(clean + "\n"), after)


def place_key(data: CommentedMap, key: str, value, after: str) -> None:
    # A new key goes after the one it belongs with, not at the end of the file.
    if key in data:
        data[key] = value
        return
    keys = list(data)
    data.insert(keys.index(after) + 1 if after in keys else len(keys), key, value)


def rename_study(project: Project, old: str, new: str) -> list[Change]:
    check_new_id(project, new)
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    studies = data["studies"]
    at = list(studies).index(old)
    comment = studies.ca.items.pop(old, None)
    studies.insert(at, new, studies.pop(old))
    if comment:
        studies.ca.items[new] = comment
    for entry in data.get("datasets") or []:
        if str(entry.get("study")) == old:
            entry["study"] = records.as_text(new)
    found = [Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)]
    relative = project.study_files.get(old)
    if relative is None:
        return found
    content = editing.open_file(project.root, relative)
    study = records.load(content.text)
    study["study"] = records.as_text(new)
    # A file named after the study takes the new name; any other name stays.
    target = (
        f"{defaults.STUDIES_DIR}/{new}.yaml" if PurePosixPath(relative).stem == old else relative
    )
    if target == relative:
        return [*found, Change(relative, records.dumped(study), content)]
    return [
        *found,
        Change(target, records.dumped(study)),
        Change(relative, "", content, removed=True),
    ]


def check_new_id(project: Project, study: str) -> None:
    if not editing.NEW_ID.fullmatch(study):
        raise EditError(
            "ID: use lower-case letters, digits and underscores, starting with a letter"
        )
    if study in project.config.studies:
        raise EditError(f"A study called {study} already exists")


def new_study(project: Project, study: str, label: str) -> list[Change]:
    check_new_id(project, study)
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    if not data.get("studies"):
        data["studies"] = CommentedMap()
    tail = records.take_tail(data["studies"])
    entry = CommentedMap()
    records.update(entry, FIELDS[0], label)
    data["studies"][study] = entry
    records.put_tail(data["studies"], tail)
    found = [Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)]
    relative = f"{defaults.STUDIES_DIR}/{study}.yaml"
    if not (project.root / relative).exists():
        found.append(Change(relative, f"{MODELINE.format('study')}\nstudy: {study}\n"))
    return found
