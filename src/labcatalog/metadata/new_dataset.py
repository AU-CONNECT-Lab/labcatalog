import csv
import io
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.codebook.core import MODELINE, read_data, template_items
from labcatalog.config import DatasetConfig, PrepareStep, dataset_by_name
from labcatalog.data.prepare import Session, StepRun, execute
from labcatalog.exceptions import EditError, MetadataError
from labcatalog.issues import Issue
from labcatalog.metadata import editing, records
from labcatalog.metadata.validate import validate_project
from labcatalog.metadata.varmap import MAP_COLUMNS
from labcatalog.project import Project, load_project, references_root

# Fields of the template that describe its own file, so a new dataset does not take them over.
OWN_FILE = ("url", "table", "files")


@dataclass
class Draft:
    template: str
    name: str
    wave: str
    snapshot_date: date


@dataclass
class Placement:
    # Where the chosen file is copied, and the file the catalog then reads.
    copy_to: str
    data_path: str
    step: PrepareStep | None = None


@dataclass
class Change:
    path: str
    text: str
    opened: editing.Opened | None = None


@dataclass
class Brought:
    created: list[str] = field(default_factory=list)
    run: StepRun | None = None


def templates(project: Project) -> list[str]:
    # Only datasets the wizard can repeat: one file, cleaned by at most one step that reads one file.
    usable = []
    for d in project.config.datasets:
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
    return Draft(template, name, wave, date.today())


def check_draft(project: Project, draft: Draft) -> None:
    if not editing.NEW_ID.fullmatch(draft.name):
        raise EditError(
            "Name: use lower-case letters, digits and underscores, starting with a letter"
        )
    if any(d.name == draft.name for d in project.config.datasets):
        raise EditError(f"A dataset called {draft.name} already exists")
    if not draft.wave.strip():
        raise EditError("Wave: fill it in")


def place(project: Project, draft: Draft, source: Path) -> Placement:
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
    old = dataset_by_name(project.config, draft.template)
    fields = old.model_dump(exclude=set(OWN_FILE))
    fields.update(name=draft.name, wave=draft.wave, path=placement.data_path)
    fields.update(snapshot_date=draft.snapshot_date)
    return DatasetConfig(**fields)


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
    instruments = list(dict.fromkeys(r["instrument"].strip() for r in rows if r["instrument"]))
    return [
        settings_change(project, draft, placement),
        map_change(draft, rows),
        study_change(project, draft, instruments),
    ]


def settings_change(project: Project, draft: Draft, placement: Placement) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    datasets = data["datasets"]
    at = next(n for n, d in enumerate(datasets) if d["name"] == draft.template)
    entry = CommentedMap()
    entry.fa.set_flow_style()
    for key, value in datasets[at].items():
        if key not in OWN_FILE:
            entry[key] = value
    entry["name"] = draft.name
    numeric = isinstance(entry.get("wave"), int) and draft.wave.isdigit()
    # A wave written as a number stays a number.
    entry["wave"] = int(draft.wave) if numeric else records.as_text(draft.wave)
    entry["path"] = placement.data_path
    entry["snapshot_date"] = draft.snapshot_date
    datasets.insert(at + 1, entry)
    if is_new_wave(project, draft):
        waves = data["studies"][entry["study"]]["waves"]
        wave = CommentedMap()
        wave.fa.set_flow_style()
        waves[entry["wave"]] = wave
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
    return Change(defaults.CONFIG_FILENAME, dumped(data), opened)


def map_change(draft: Draft, rows: list[dict[str, str]]) -> Change:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(MAP_COLUMNS)
    writer.writerows((r["column"], r["instrument"].strip(), r["item"].strip()) for r in rows)
    return Change(f"{defaults.MAPS_DIR}/{draft.name}.csv", out.getvalue())


def study_change(project: Project, draft: Draft, instruments: list[str]) -> Change:
    study = dataset_by_name(project.config, draft.template).study
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
    return Change(relative, dumped(data), opened)


def flow_list(values: list[str]) -> CommentedSeq:
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def dumped(data: CommentedMap) -> str:
    out = io.StringIO()
    records.round_trip().dump(data, out)
    return out.getvalue()


def is_new_wave(project: Project, draft: Draft) -> bool:
    study = dataset_by_name(project.config, draft.template).study
    return draft.wave not in project.config.studies[study].waves


def check(project: Project, found: list[Change]) -> list[Issue]:
    issues = [issue for change in found for issue in editing.check_text(change.path, change.text)]
    return issues or new_issues(project, found)


def new_issues(project: Project, found: list[Change]) -> list[Issue]:
    # Checks across files, on copies of the settings without the data, so only new problems count.
    before = {same(i) for i in copy_issues(project, [])}
    after = copy_issues(project, found)
    return [i for i in after if i.level == "error" and same(i) not in before]


def same(issue: Issue) -> tuple[str, str]:
    # An inserted dataset shifts the numbers of the entries after it.
    return issue.code, re.sub(r"\[\d+\]", "[]", issue.message)


def copy_issues(project: Project, found: list[Change]) -> list[Issue]:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        shutil.copyfile(project.root / defaults.CONFIG_FILENAME, root / defaults.CONFIG_FILENAME)
        for folder in (defaults.INSTRUMENTS_DIR, defaults.STUDIES_DIR, defaults.MAPS_DIR):
            if (project.root / folder).is_dir():
                shutil.copytree(project.root / folder, root / folder)
        bib = references_root(project.config, project.root) / defaults.BIB_FILENAME
        if bib.is_file():
            target = references_root(project.config, root) / defaults.BIB_FILENAME
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bib, target)
        for change in found:
            path = root / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.text, encoding="utf-8")
        try:
            issues = validate_project(load_project(root))
        except MetadataError as err:
            issues = err.issues
        # Each copy has its own folder, which some messages name.
        return [i.model_copy(update={"message": i.message.replace(str(root), "")}) for i in issues]


def write(project: Project, found: list[Change]) -> None:
    # Every file is checked first, so a refused save leaves all of them as they were.
    for change in found:
        if change.opened is not None:
            path = project.root / change.opened.path
            if path.stat().st_mtime_ns != change.opened.modified:
                raise EditError(f"{change.path} changed on disk meanwhile; start again")
        elif (project.root / change.path).exists():
            raise EditError(f"{change.path} already exists")
    for change in found:
        if change.opened is not None:
            editing.save_file(project.root, change.opened, change.text)
        else:
            path = project.root / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.text, encoding="utf-8", newline="\n")
