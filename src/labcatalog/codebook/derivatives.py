import csv
import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from labcatalog import defaults
from labcatalog.codebook.core import MAP_COLUMNS, MODELINE, dump, flow, yaml_text
from labcatalog.config import PrepareStep, TableStep
from labcatalog.exceptions import CodebookError
from labcatalog.paths import expand_path, portable_path
from labcatalog.project import Project, load_project

ROW_NAME = "bids_name"
SUBJECT_COLUMN = "participant_id"
SESSION_COLUMN = "session_id"
KEY_COLUMNS = (ROW_NAME, SUBJECT_COLUMN, SESSION_COLUMN)
NOT_AVAILABLE = ("n/a", "")
# The prepare step that takes a table in again is named after it: table_fnirs_qc.
TABLE_STEP = "table_"
ENTITY = re.compile(r"^([A-Za-z]+)-([A-Za-z0-9]+)$")
HEADER = (
    "# Written by labcatalog from {table}. Taking the table again rewrites the items; "
    "the other fields and your changes to an item's text stay."
)


@dataclass
class Derived:
    written: list[Path] = field(default_factory=list)
    # Columns that are not numbers, so they are not items.
    left_out: list[str] = field(default_factory=list)
    steps: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Request:
    table: Path
    name: str
    study: str
    modality: str
    reporter: str
    split: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    wave: str | None = None
    label: str | None = None


def run_derivatives(root: Path, request: Request) -> Derived:
    return derive(load_project(root), request)


def table_request(table: TableStep, root: Path) -> Request:
    return Request(
        expand_path(table.path, root),
        table.name,
        table.study,
        table.modality,
        table.reporter,
        table.split,
        table.columns,
        table.wave,
        table.label,
    )


def table_step(request: Request, root: Path, done: Derived) -> PrepareStep:
    # Reads the table and its sidecars and writes the data files, so Run outdated follows the table.
    def stored(path: Path) -> str:
        return portable_path(path, root).as_posix()

    table = TableStep(
        path=stored(request.table),
        name=request.name,
        study=request.study,
        modality=request.modality,
        reporter=request.reporter,
        split=request.split,
        columns=request.columns,
        wave=request.wave,
        label=request.label,
    )
    return PrepareStep(
        name=f"{TABLE_STEP}{request.name}",
        table=table,
        inputs=[stored(p) for p in [request.table, *sidecars(request.table)]],
        outputs=[stored(p) for p in done.written if p.parent.name == defaults.DATA_DIR],
        stage="extract",
    )


def derive(project: Project, request: Request) -> Derived:
    table = read_table(request.table)
    keys = row_keys(table, request)
    sidecar = read_sidecar(request.table)
    measures, left_out = measure_columns(table, request.columns, sidecar)
    if not measures:
        raise CodebookError(f"No numeric columns to take from {request.table.name}")
    groups = sorted({tuple(row[e] for e in request.split) for _, row in keys.iterrows()})
    done = Derived(left_out=left_out)
    instruments = {}
    for group in groups:
        instrument_id = identifier("_".join([request.name, *group]))
        path = project.root / defaults.INSTRUMENTS_DIR / f"{instrument_id}.yaml"
        text = instrument_text(project, request, instrument_id, group, measures, sidecar, path)
        write_text(path, text)
        done.written.append(path)
        instruments[group] = instrument_id
    datasets = {}
    for wave in sorted(keys["wave"].unique(), key=wave_order):
        dataset = f"{request.name}_w{wave}"
        rows = keys["wave"] == wave
        data_path = project.root / defaults.DATA_DIR / f"{dataset}.csv"
        write_data(project, data_path, table[rows], keys[rows], request.split, measures)
        map_path = project.root / defaults.MAPS_DIR / f"{dataset}.csv"
        write_map(project, map_path, groups, instruments, measures)
        done.written += [data_path, map_path]
        datasets[dataset] = (wave, data_path)
    done.steps = registration(project, request, datasets, list(instruments.values()))
    return done


def read_table(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError) as err:
        raise CodebookError(f"Cannot read {path}: {err}") from None


def row_keys(table: pd.DataFrame, request: Request) -> pd.DataFrame:
    # One row of BIDS entities (sub, ses, task, ...) for each row of the table.
    if ROW_NAME in table:
        keys = pd.DataFrame([entities(name) for name in table[ROW_NAME]], index=table.index)
    elif SUBJECT_COLUMN in table:
        keys = pd.DataFrame(index=table.index)
        keys["sub"] = table[SUBJECT_COLUMN].str.removeprefix("sub-")
        if SESSION_COLUMN in table:
            keys["ses"] = table[SESSION_COLUMN].str.removeprefix("ses-")
    else:
        raise CodebookError(
            f"{request.table.name} needs a {ROW_NAME} or {SUBJECT_COLUMN} column to name the rows"
        )
    missing = [e for e in request.split if e not in keys]
    if missing:
        raise CodebookError(f"The rows have no {', '.join(missing)} entity to split by")
    if "ses" in keys and keys["ses"].notna().all():
        keys["wave"] = keys["ses"].map(wave_name)
    elif request.wave is not None:
        keys["wave"] = request.wave
    else:
        raise CodebookError(f"The rows of {request.table.name} name no session; give the Wave")
    keys = keys.fillna("")
    where = ["sub", "wave", *request.split]
    repeated = keys[keys.duplicated(where, keep=False)]
    if not repeated.empty:
        varying = [
            c for c in keys if c not in where and repeated.groupby(where)[c].nunique().gt(1).any()
        ]
        first = repeated.iloc[0]
        raise CodebookError(
            f"Several rows for sub-{first['sub']} in wave {first['wave']}"
            + (f"; split them by {', '.join(varying)}" if varying else "")
        )
    return keys


def entities(name: str) -> dict[str, str]:
    # The last part without a dash, such as "bold", is the suffix and names no entity.
    found = {}
    for part in Path(name).name.split("_"):
        match = ENTITY.match(part)
        if match:
            found[match[1]] = match[2]
    if "sub" not in found:
        raise CodebookError(f"{name} names no subject (sub-)")
    return found


def wave_name(session: str) -> str:
    # ses-01 is wave 1; a session named by a word keeps the word.
    return str(int(session)) if session.isdigit() else session


def wave_order(wave: str) -> tuple:
    return (0, int(wave), "") if wave.isdigit() else (1, 0, wave)


def measure_columns(
    table: pd.DataFrame, patterns: list[str], sidecar: dict[str, Any]
) -> tuple[list[str], list[str]]:
    candidates = [c for c in table if c not in KEY_COLUMNS]
    if patterns:
        candidates = [c for c in candidates if any(fnmatch.fnmatchcase(c, p) for p in patterns)]
    # A column whose sidecar lists its Levels is a choice, numbers or not.
    taken = [c for c in candidates if levels_of(sidecar, c) or is_numeric(table[c])]
    return taken, [c for c in candidates if c not in taken]


def levels_of(sidecar: dict[str, Any], column: str) -> dict[str, str]:
    # BIDS gives a level as its label, or as an object with a Description.
    entry = sidecar.get(column)
    found = entry.get("Levels") if isinstance(entry, dict) else None
    if not isinstance(found, dict):
        return {}
    return {
        str(key): value if isinstance(value, str) else str(value.get("Description", key))
        for key, value in found.items()
    }


def is_numeric(values: pd.Series) -> bool:
    given = values[~values.isin(NOT_AVAILABLE)]
    return not given.empty and pd.to_numeric(given, errors="coerce").notna().all()


def read_sidecar(table: Path) -> dict[str, Any]:
    # BIDS inheritance: the sidecars nearer the table, and naming more of its entities, win.
    found: dict[str, Any] = {}
    for path in sidecars(table):
        try:
            found.update(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as err:
            raise CodebookError(f"{path.name} is not valid JSON: {err}") from None
    return found


def sidecars(table: Path) -> list[Path]:
    own = table.with_suffix(".json")
    parts = table.stem.split("_")
    if ENTITY.match(parts[-1]):
        # Without a suffix, nothing above the table describes it.
        return [own] if own.is_file() else []
    suffix, entities = parts[-1], set(parts[:-1])
    # Up to the pipeline's folder, the one with dataset_description.json; else the table's own.
    folders = []
    for folder in table.resolve().parents:
        folders.append(folder)
        if (folder / "dataset_description.json").is_file():
            break
    else:
        folders = [table.resolve().parent]
    found = []
    for depth, folder in enumerate(reversed(folders)):
        for path in folder.glob(f"*{suffix}.json"):
            named = path.stem.split("_")
            if named[-1] == suffix and set(named[:-1]) <= entities:
                found.append((depth, len(named), path))
    return [path for _, _, path in sorted(found)]


def generated_by(table: Path, root: Path) -> str | None:
    # The pipeline that wrote the table, from the dataset_description.json above it.
    for folder in table.resolve().parents:
        description = folder / "dataset_description.json"
        if description.is_file():
            found = json.loads(description.read_text(encoding="utf-8"))
            for tool in found.get("GeneratedBy", []):
                return " ".join(filter(None, (tool.get("Name"), tool.get("Version"))))
            return found.get("Name")
        if folder == root.resolve():
            return None
    return None


def identifier(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_")


def instrument_text(
    project: Project,
    request: Request,
    instrument_id: str,
    group: tuple[str, ...],
    measures: list[str],
    sidecar: dict[str, Any],
    path: Path,
) -> str:
    old = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    kept = {i["id"]: i for i in old.get("items", [])} if old else {}
    items = [kept.get(identifier(c)) or item(c, sidecar) for c in measures]
    sets = response_sets(sidecar, measures)
    if old:
        document = {**old, "items": items}
        held = {s["id"] for s in old.get("response_sets", [])}
        added = [s for s in sets if s["id"] not in held]
        if added:
            document["response_sets"] = [*old.get("response_sets", []), *added]
    else:
        name = request.label or request.name
        source = generated_by(request.table, project.root)
        document = {
            "id": instrument_id,
            "name": f"{name}: {', '.join(group)}" if group else name,
            "modality": request.modality,
            "description": f"Measures from {source or request.table.name}"
            + (f" for {', '.join(group)}." if group else "."),
            **({"response_sets": sets} if sets else {}),
            "items": items,
        }
    table = portable_path(request.table.resolve(), project.root.resolve()).as_posix()
    modeline, rest = yaml_text(document, "instrument").split("\n", 1)
    return f"{modeline}\n{HEADER.format(table=table)}\n{rest}"


def item(column: str, sidecar: dict[str, Any]) -> dict[str, Any]:
    entry = sidecar.get(column, {})
    text = entry.get("Description") or entry.get("LongName") or column
    if entry.get("Units"):
        text = f"{text} ({entry['Units']})"
    fields: dict[str, Any] = {"id": identifier(column)}
    if entry.get("LongName"):
        fields["label"] = entry["LongName"]
    if levels_of(sidecar, column):
        return {**fields, "text": text, "response_set": set_id(sidecar, column)}
    return {**fields, "text": text, "type": "number"}


def set_id(sidecar: dict[str, Any], column: str) -> str:
    # Columns with the same levels share the set named after the first of them.
    levels = levels_of(sidecar, column)
    first = next(c for c in sidecar if levels_of(sidecar, c) == levels)
    return identifier(first)


def response_sets(sidecar: dict[str, Any], measures: list[str]) -> list[dict[str, Any]]:
    sets = {}
    for column in measures:
        levels = levels_of(sidecar, column)
        if levels:
            options = [{"value": option_value(k), "label": v} for k, v in levels.items()]
            sets.setdefault(set_id(sidecar, column), options)
    return [{"id": key, "options": options} for key, options in sets.items()]


def option_value(key: str) -> int | float | str:
    try:
        number = float(key)
    except ValueError:
        return key
    return int(number) if number.is_integer() else number


def column_name(group: tuple[str, ...], measure: str) -> str:
    return "_".join([*group, measure])


def write_data(
    project: Project,
    path: Path,
    table: pd.DataFrame,
    keys: pd.DataFrame,
    split: list[str],
    measures: list[str],
) -> None:
    rows: dict[str, dict[str, str]] = {}
    for (_, values), (_, key) in zip(table.iterrows(), keys.iterrows(), strict=True):
        row = rows.setdefault(key["sub"], {})
        group = tuple(key[e] for e in split)
        for measure in measures:
            value = values[measure]
            row[column_name(group, measure)] = "" if value in NOT_AVAILABLE else value
    columns = sorted({c for row in rows.values() for c in row})
    id_column = project.config.defaults.id_column
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow([id_column, *columns])
        for subject in sorted(rows):
            writer.writerow([f"sub-{subject}", *(rows[subject].get(c, "") for c in columns)])


def write_map(
    project: Project,
    path: Path,
    groups: list[tuple[str, ...]],
    instruments: dict[tuple[str, ...], str],
    measures: list[str],
) -> None:
    rows = [(project.config.defaults.id_column, "", "")]
    rows += [(column_name(g, m), instruments[g], identifier(m)) for g in groups for m in measures]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(MAP_COLUMNS)
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def registration(
    project: Project,
    request: Request,
    datasets: dict[str, tuple[str, Path]],
    instrument_ids: list[str],
) -> list[tuple[str, str]]:
    # What the user adds by hand once, as for an imported codebook.
    known = {d.name for d in project.config.datasets}
    entries = [
        flow(
            {
                "name": name,
                "modality": request.modality,
                "study": request.study,
                "wave": int(wave) if wave.isdigit() else wave,
                "reporter": request.reporter,
                "source": "csv",
                "path": path.relative_to(project.root).as_posix(),
            }
        )
        for name, (wave, path) in datasets.items()
        if name not in known
    ]
    steps = []
    study = project.config.studies.get(request.study)
    listed = set(study.waves) if study else set()
    waves = [w for w in dict.fromkeys(w for w, _ in datasets.values()) if w not in listed]
    if waves:
        steps.append(
            (
                f"In {defaults.CONFIG_FILENAME}, add under studies, {request.study}, waves:",
                "\n".join(f"  {dump({int(w) if w.isdigit() else w: {}})}" for w in waves),
            )
        )
    if entries:
        lines = "\n".join(f"  - {e}" for e in entries)
        steps.append((f"In {defaults.CONFIG_FILENAME}, add under datasets:", lines))
    content = project.studies.get(request.study)
    location = project.study_files.get(
        request.study, f"{defaults.STUDIES_DIR}/{request.study}.yaml"
    )
    given = {a.instrument: a for a in content.administrations} if content else {}
    added, changed = [], []
    for instrument_id in instrument_ids:
        administration = given.get(instrument_id)
        if administration is None:
            added.append(flow({"instrument": instrument_id, "datasets": list(datasets)}))
        elif missing := [d for d in datasets if d not in administration.datasets]:
            fields = administration.model_dump(exclude_defaults=True)
            fields["datasets"] = [*administration.datasets, *missing]
            changed.append(flow(fields))
    if content is None and added:
        lines = [MODELINE.format("study"), dump({"study": request.study}), "administrations:"]
        steps.append(
            (f"Create {location} with:", "\n".join([*lines, *(f"  - {a}" for a in added)]))
        )
        return steps
    if added:
        steps.append(
            (f"In {location}, add under administrations:", "\n".join(f"  - {a}" for a in added))
        )
    if changed:
        steps.append(
            (
                f"In {location}, replace these administrations with:",
                "\n".join(f"  - {c}" for c in changed),
            )
        )
    return steps
