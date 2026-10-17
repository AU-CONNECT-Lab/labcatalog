import csv
import io
import re
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.codebook.core import MODELINE, read_data, template_items
from labcatalog.config import DatasetConfig, PrepareStep, dataset_by_name
from labcatalog.data.prepare import Session, StepRun, execute
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing, records
from labcatalog.metadata.changes import Change
from labcatalog.metadata.varmap import MAP_COLUMNS
from labcatalog.paths import portable_path
from labcatalog.project import Project
from labcatalog.sources.folder_source import ID, file_pattern

# Fields of the template that describe its own file, so a new dataset does not take them over.
OWN_FILE = ("url", "table", "files")
# The order a dataset that repeats none is written in, as in the example project.
BLANK_KEYS = (
    "name",
    "modality",
    "study",
    "wave",
    "reporter",
    "source",
    "path",
    "files",
    "wave_column",
    "id_column",
    "date_column",
    "snapshot_date",
)


@dataclass
class Blank:
    # What a dataset that repeats none is, filled in by hand.
    study: str
    modality: str
    reporter: str
    id_column: str | None = None
    date_column: str | None = None
    wave_column: str | None = None


@dataclass
class Draft:
    # Empty when the dataset repeats none and `blank` says what it is.
    template: str
    name: str
    wave: str
    snapshot_date: date
    blank: Blank | None = None
    # Set for a folder of files: which files to count, with {id} where the path holds the ID.
    files: str | None = None


@dataclass
class Placement:
    # Where the chosen file is copied, and the file the catalog then reads; a folder is not copied.
    copy_to: str | None
    data_path: str
    step: PrepareStep | None = None


@dataclass
class FolderPreview:
    people: int
    files: int
    unmatched: list[str]


@dataclass
class WaveRows:
    rows: int
    waves: list[str]


@dataclass
class Brought:
    created: list[str] = field(default_factory=list)
    run: StepRun | None = None


def templates(project: Project) -> list[str]:
    # Repeatable: a folder, a file of every wave, or one file cleaned by at most one step.
    usable = []
    for d in project.config.datasets:
        if d.source == "folder" or d.wave_column:
            usable.append(d.name)
            continue
        try:
            placement_for(project, d.name, f"{d.name}_next", ".csv")
        except EditError:
            continue
        usable.append(d.name)
    return usable


def suggest(project: Project, template: str) -> Draft:
    old = dataset_by_name(project.config, template)
    wave = str(int(old.wave) + 1) if old.wave.isdigit() else old.wave
    name = template
    if old.wave.isdigit() and template.endswith(old.wave):
        name = template[: -len(old.wave)] + wave
    files = suggest_files(project, template, wave) if old.source == "folder" else None
    return Draft(template, name, wave, date.today(), files=files)


def suggest_files(project: Project, template: str, wave: str) -> str:
    # A folder's files rule usually names the wave too, as in ses-1.
    old = dataset_by_name(project.config, template)
    return renamed(old.files, old.wave, wave)


def suggest_blank(project: Project, study: str) -> Draft:
    config = project.config
    waves = list(config.studies[study].waves) if study in config.studies else []
    blank = Blank(study, config.vocab.modalities[0], (config.vocab.reporters or [""])[0])
    return Draft("", "", waves[0] if waves else "1", date.today(), blank)


def is_folder(draft: Draft) -> bool:
    return draft.files is not None


def repeats_long_file(project: Project, draft: Draft) -> bool:
    # A file with a wave column holds the next wave too, so the new dataset reads it again.
    return draft.blank is None and bool(dataset_by_name(project.config, draft.template).wave_column)


def wave_rows(project: Project, dataset: DatasetConfig) -> WaveRows:
    frame = read_data(project, dataset)
    if dataset.wave_column not in frame:
        raise EditError(f"{dataset.path} has no column {dataset.wave_column}")
    values = frame[dataset.wave_column]
    return WaveRows(int((values == dataset.wave).sum()), sorted(set(values)))


def folder_files(folder: Path) -> list[str]:
    # Paths, not contents, as the folder source counts them.
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if not p.is_dir())


def preview_folder(paths: list[str], files: str) -> FolderPreview:
    if files.count(ID) != 1:
        raise EditError("Files: put {id} once, where each file's path holds the ID")
    matcher = file_pattern(files)
    people = set()
    unmatched = []
    for path in paths:
        found = matcher.fullmatch(path)
        if found:
            people.add(found.group("id"))
        else:
            unmatched.append(path)
    return FolderPreview(len(people), len(paths) - len(unmatched), unmatched)


def study_of(project: Project, draft: Draft) -> str:
    if draft.blank is not None:
        return draft.blank.study
    return dataset_by_name(project.config, draft.template).study


def check_draft(project: Project, draft: Draft) -> None:
    if not editing.NEW_ID.fullmatch(draft.name):
        raise EditError(
            "Name: use lower-case letters, digits and underscores, starting with a letter"
        )
    if any(d.name == draft.name for d in project.config.datasets):
        raise EditError(f"A dataset called {draft.name} already exists")
    if not draft.wave.strip():
        raise EditError("Wave: fill it in")


def place(project: Project, draft: Draft, source: Path | None) -> Placement:
    if repeats_long_file(project, draft):
        return Placement(None, dataset_by_name(project.config, draft.template).path)
    if is_folder(draft):
        # A path typed relative, or with ~ or a variable, is kept as typed.
        path = portable_path(source, project.root) if source.is_absolute() else source
        return Placement(None, path.as_posix())
    if draft.blank is not None:
        path = f"{defaults.DATA_DIR}/{draft.name}{source.suffix}"
        placement = Placement(path, path)
    else:
        placement = placement_for(project, draft.template, draft.name, source.suffix)
    for path in {placement.copy_to, placement.data_path}:
        if (project.root / path).exists():
            raise EditError(f"{path} already exists; move it away or choose another name")
    return placement


def placement_for(project: Project, template: str, name: str, suffix: str) -> Placement:
    old = dataset_by_name(project.config, template)
    if old.source != "csv" or not old.path:
        raise EditError(f"{template} is read from a folder of files, not one file")
    step = next((s for s in project.config.prepare if old.path in s.outputs), None)
    if step is None:
        path = renamed(old.path, template, name)
        if path == old.path:
            path = (Path(old.path).parent / f"{name}{suffix}").as_posix()
        return Placement(path, path)
    new = PrepareStep(
        name=renamed(step.name, template, name),
        run=renamed(step.run, template, name),
        inputs=[renamed(p, template, name) for p in step.inputs],
        outputs=[renamed(p, template, name) for p in step.outputs],
    )
    changed = [p for p, q in zip(new.inputs, step.inputs, strict=True) if p != q]
    files = [p for p in changed if Path(p).suffix]
    data_path = renamed(old.path, template, name)
    if len(files) != 1 or data_path not in new.outputs or new.name == step.name:
        raise EditError(
            f"{template} is made by the prepare step {step.name}, which does not read one file "
            f"named after {template}; ask whoever wrote the step to add {name}"
        )
    return Placement(files[0], data_path, new)


def renamed(text: str, old: str, new: str) -> str:
    return re.sub(rf"(?<![A-Za-z0-9]){re.escape(old)}(?![A-Za-z0-9])", new, text)


def bring_in(project: Project, source: Path, placement: Placement) -> Brought:
    # Copies the file in and runs the cleaning step; the caller removes `created` on cancel.
    root = project.root
    brought = Brought()
    target = root / placement.copy_to
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    brought.created.append(placement.copy_to)
    if placement.step is not None:
        fresh = [p for p in placement.step.outputs if not (root / p).exists()]
        brought.run = StepRun(placement.step.name, placement.step.run)
        execute(placement.step, root, brought.run, Session(), None, None, None)
        brought.created += [p for p in fresh if (root / p).exists()]
    return brought


def remove(project: Project, created: list[str]) -> None:
    for path in created:
        (project.root / path).unlink(missing_ok=True)


def dataset_config(project: Project, draft: Draft, placement: Placement) -> DatasetConfig:
    if draft.blank is not None:
        return DatasetConfig(
            name=draft.name,
            modality=draft.blank.modality,
            study=draft.blank.study,
            wave=draft.wave,
            reporter=draft.blank.reporter,
            source="folder" if is_folder(draft) else "csv",
            path=placement.data_path,
            files=draft.files,
            id_column=own_id_column(project, draft.blank),
            date_column=draft.blank.date_column,
            wave_column=draft.blank.wave_column,
            snapshot_date=draft.snapshot_date,
        )
    old = dataset_by_name(project.config, draft.template)
    fields = old.model_dump(exclude=set(OWN_FILE))
    fields.update(name=draft.name, wave=draft.wave, path=placement.data_path, files=draft.files)
    fields.update(snapshot_date=draft.snapshot_date)
    return DatasetConfig(**fields)


def own_id_column(project: Project, blank: Blank) -> str | None:
    # Written only when it is not the project's usual ID column.
    usual = project.config.defaults.id_column
    return blank.id_column if blank.id_column and blank.id_column != usual else None


def file_columns(project: Project, dataset: DatasetConfig) -> list[str]:
    return [str(c) for c in read_data(project, dataset).columns]


def match_columns(project: Project, dataset: DatasetConfig) -> list[dict[str, str]]:
    # Only matches with an item of a catalogued instrument; the rest are left for a person.
    rows = template_items(project, dataset, read_data(project, dataset))
    known = {(i.id, item.id) for i in project.instruments.values() for item in i.items}
    return [
        {
            "column": row["column"],
            "instrument": row["instrument"] if (row["instrument"], row["item"]) in known else "",
            "item": row["item"] if (row["instrument"], row["item"]) in known else "",
        }
        for row in rows
    ]


def template_rows(project: Project, template: str) -> list[dict[str, str]]:
    # A file of every wave holds the next wave in the template's own columns.
    return [
        {"column": e.column, "instrument": e.instrument or "", "item": e.item or ""}
        for e in project.maps.get(template, [])
    ]


def coverage(
    project: Project, template: str, rows: list[dict[str, str]]
) -> dict[str, tuple[int, int]]:
    # Items found per instrument, for the instruments the template or the new file has.
    found: dict[str, set[str]] = {}
    for row in rows:
        if row["instrument"]:
            found.setdefault(row["instrument"], set()).add(row["item"])
    before = {e.instrument for e in project.maps.get(template, []) if e.instrument}
    return {
        instrument_id: (
            len(found.get(instrument_id, set())),
            len(project.instruments[instrument_id].items),
        )
        for instrument_id in [*sorted(before), *sorted(set(found) - before)]
        if instrument_id in project.instruments
    }


def check_rows(project: Project, rows: list[dict[str, str]]) -> list[str]:
    problems = []
    for row in rows:
        instrument_id, item = row["instrument"].strip(), row["item"].strip()
        if not (instrument_id or item):
            continue
        if instrument_id not in project.instruments:
            problems.append(f"{row['column']}: no instrument {instrument_id or '(empty)'}")
        elif item not in {i.id for i in project.instruments[instrument_id].items}:
            problems.append(f"{row['column']}: {instrument_id} has no item {item or '(empty)'}")
    return problems


def changes(
    project: Project, draft: Draft, placement: Placement, rows: list[dict[str, str]]
) -> list[Change]:
    if is_folder(draft):
        # A folder's only column counts files, so there is nothing to map or administer.
        return [settings_change(project, draft, placement)]
    instruments = list(dict.fromkeys(r["instrument"].strip() for r in rows if r["instrument"]))
    return [
        settings_change(project, draft, placement),
        map_change(draft, rows),
        study_change(project, draft, instruments),
    ]


def settings_change(project: Project, draft: Draft, placement: Placement) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    if not data.get("datasets"):
        data["datasets"] = CommentedSeq()
    datasets = data["datasets"]
    study = data["studies"][study_of(project, draft)]
    entry = CommentedMap()
    entry.fa.set_flow_style()
    if draft.blank is None:
        at = next(n for n, d in enumerate(datasets) if d["name"] == draft.template)
        for key, value in datasets[at].items():
            if key == "files" and is_folder(draft):
                entry[key] = draft.files
            elif key not in OWN_FILE:
                entry[key] = value
        numeric = isinstance(entry.get("wave"), int)
    else:
        # After the study's other datasets, or last when it has none yet.
        mine = [n for n, d in enumerate(datasets) if str(d.get("study")) == draft.blank.study]
        at = mine[-1] if mine else len(datasets) - 1
        fields = dataset_config(project, draft, placement).model_dump(exclude_none=True)
        for key in BLANK_KEYS:
            if key in fields:
                entry[key] = records.as_text(fields[key])
        numeric = all(isinstance(key, int) for key in study.get("waves") or {})
    entry["name"] = draft.name
    # A wave written as a number stays a number.
    entry["wave"] = (
        int(draft.wave) if numeric and draft.wave.isdigit() else records.as_text(draft.wave)
    )
    entry["path"] = placement.data_path
    entry["snapshot_date"] = draft.snapshot_date
    datasets.insert(at + 1, entry)
    if is_new_wave(project, draft):
        # Whatever follows the study, such as the next section's comment, stays after it.
        tail = records.take_tail(study)
        if not study.get("waves"):
            study["waves"] = CommentedMap()
        wave = CommentedMap()
        wave.fa.set_flow_style()
        study["waves"][entry["wave"]] = wave
        records.put_tail(study, tail)
    if placement.step is not None:
        steps = data["prepare"]
        old = dataset_by_name(project.config, draft.template).path
        after = next(n for n, s in enumerate(steps) if old in s["outputs"])
        step = CommentedMap()
        step.fa.set_flow_style()
        step["name"] = placement.step.name
        step["run"] = placement.step.run
        step["inputs"] = flow_list(placement.step.inputs)
        step["outputs"] = flow_list(placement.step.outputs)
        steps.insert(after + 1, step)
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def map_change(draft: Draft, rows: list[dict[str, str]]) -> Change:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(MAP_COLUMNS)
    writer.writerows((r["column"], r["instrument"].strip(), r["item"].strip()) for r in rows)
    return Change(f"{defaults.MAPS_DIR}/{draft.name}.csv", out.getvalue())


def study_change(project: Project, draft: Draft, instruments: list[str]) -> Change:
    study = study_of(project, draft)
    relative = project.study_files.get(study, f"{defaults.STUDIES_DIR}/{study}.yaml")
    if (project.root / relative).exists():
        opened = editing.open_file(project.root, relative)
        data = records.load(opened.text)
    else:
        opened = None
        data = records.load(f"{MODELINE.format('study')}\nstudy: {study}\n")
    if not data.get("administrations"):
        data["administrations"] = CommentedSeq()
    administrations = data["administrations"]
    for instrument_id in instruments:
        mine = [a for a in administrations if a["instrument"] == instrument_id]
        # The administration that already holds the template, so its target and the rest carry over.
        entry = next((a for a in mine if draft.template in a.get("datasets", [])), None)
        entry = entry or (mine[0] if mine else None)
        if entry is None:
            entry = CommentedMap()
            entry.fa.set_flow_style()
            entry["instrument"] = instrument_id
            entry["datasets"] = flow_list([])
            administrations.append(entry)
        if draft.name not in entry["datasets"]:
            entry["datasets"].append(draft.name)
    return Change(relative, records.dumped(data), opened)


def flow_list(values: list[str]) -> CommentedSeq:
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def is_new_wave(project: Project, draft: Draft) -> bool:
    return draft.wave not in project.config.studies[study_of(project, draft)].waves
