from dataclasses import dataclass
from datetime import date

from ruamel.yaml.comments import CommentedMap

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


def new_study(project: Project, study: str, label: str) -> list[Change]:
    if not editing.NEW_ID.fullmatch(study):
        raise EditError(
            "ID: use lower-case letters, digits and underscores, starting with a letter"
        )
    if study in project.config.studies:
        raise EditError(f"A study called {study} already exists")
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
