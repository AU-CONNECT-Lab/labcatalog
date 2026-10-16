import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

import pandas as pd
import yaml

from labcatalog import defaults, qualtrics, redcap
from labcatalog.config import DatasetConfig, dataset_by_name, id_column_for, missing_codes_for
from labcatalog.datalad.annex import fetch_advice, is_placeholder
from labcatalog.exceptions import CodebookError
from labcatalog.issues import Issue, IssueLevel, has_errors
from labcatalog.project import Project
from labcatalog.schema import ItemType, Score
from labcatalog.sources import get_source
from labcatalog.varmap import MAP_COLUMNS

ITEMS = "items.csv"
INSTRUMENTS = "instruments.csv"
SCORES = "scores.csv"

# What each column holds; the Import page shows these and the AI prompt quotes them.
COLUMNS: dict[str, dict[str, str]] = {
    ITEMS: {
        "column": "the data file's column name; already filled in, do not change it",
        "instrument": "ID of the instrument (questionnaire) the column belongs to; empty for columns that are not items, such as the ID or a date",
        "item": "ID of the item within its instrument; for a column holding a score the data already has, score: and the score ID (score:cesd_total)",
        "text": "the item's wording",
        "type": "choice (answered with response options; the default), number (an amount such as age) or text (an open answer)",
        "choices": "for a choice item, each value and its label, separated by semicolons: 0=Never; 1=Sometimes; 2=Often",
        "reverse": "yes for a reverse-scored item",
        "min": "the lowest allowed value of a number item",
        "max": "the highest allowed value of a number item",
    },
    INSTRUMENTS: {
        "instrument": "the instrument ID used in items.csv",
        "name": "the instrument's full name",
        "abbreviation": "its usual abbreviation",
        "kind": "questionnaire (the default) or demographics",
        "construct": "what it measures",
    },
    SCORES: {
        "instrument": "the instrument ID used in items.csv",
        "score": "ID of the score",
        "label": "the score's name, such as Total or Anxiety",
        "method": "sum or mean",
        "items": "the item IDs in the score, separated by semicolons; first-last means every item from first to last in items.csv order (cesd_1-cesd_20)",
        "missing_rule": "complete (no score unless every item is answered; the default), prorate (missing items take the mean of the answered ones) or zero (missing items count as 0)",
        "min_valid": "with prorate, the fewest answered items that still give a score",
    },
}

PROMPT = """\
I am entering a codebook into labcatalog, a tool that catalogs a lab's questionnaires. Using the codebook I attach or paste below, fill in three CSV files that describe the columns of one data file: {dataset} (study {study}, wave {wave}, reporter {reporter}).

{format}

Rules:
- Keep every row of items.csv in the same order, and do not change the column cells. Rows that already have an instrument and item are a first guess; correct them.
- IDs (instrument, item, score) use only letters, digits and underscores. An item ID should not carry the wave (eps_1, not eps_1_w2).
- Take wording, response options and scoring only from the codebook. Where it does not say, leave the cell empty; do not guess.
- These instruments are already in the project. Reuse their IDs; for them only column, instrument and item matter in items.csv, and they need no rows in instruments.csv or scores.csv.
{known}
- Answer with exactly three csv code blocks, in the order items.csv, instruments.csv, scores.csv, each starting with its header row. Put a cell in double quotes when it contains a comma or a double quote.

items.csv as it is now:

```csv
{items}
```
"""

ID_PATTERN = re.compile(r"[A-Za-z0-9_]+")
INTEGER = re.compile(r"-?\d+")
DECIMAL = re.compile(r"-?\d*\.\d+")
YES = {"yes", "y", "true", "1"}
NO = {"", "no", "n", "false", "0"}
ITEM_TYPES = get_args(ItemType)
METHODS = get_args(Score.model_fields["method"].annotation)
MISSING_RULES = get_args(Score.model_fields["missing_rule"].annotation)
FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
MODELINE = "# yaml-language-server: $schema=../schemas/{}.schema.json"

Value = int | float | str
Options = tuple[tuple[Value, str], ...]


@dataclass
class ImportResult:
    issues: list[Issue]
    written: list[Path] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    # Each step is an instruction and the YAML lines it asks for.
    steps: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DraftItem:
    id: str
    text: str
    type: str
    options: Options
    reverse: bool
    min: Value | None
    max: Value | None


@dataclass
class Draft:
    id: str
    line: int
    items: dict[str, DraftItem] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)
    scores: list[dict[str, Any]] = field(default_factory=list)


def codebook_paths(project: Project, dataset: str) -> dict[str, Path]:
    folder = project.root / defaults.CODEBOOK_DIR / dataset
    return {name: folder / name for name in COLUMNS}


def unmapped_datasets(project: Project) -> list[str]:
    return [d.name for d in project.config.datasets if d.name not in project.maps]


def require_unmapped(project: Project, dataset: str) -> None:
    if dataset in unmapped_datasets(project):
        return
    if dataset in project.maps:
        raise CodebookError(f"{dataset} already has a column map in {defaults.MAPS_DIR}/")
    raise CodebookError(f"No dataset named {dataset} in {defaults.CONFIG_FILENAME}")


def write_templates(
    project: Project, dataset_name: str, dictionary: Path | None = None
) -> list[Path]:
    paths = codebook_paths(project, dataset_name)
    if any(path.exists() for path in paths.values()):
        folder = relative(project, paths[ITEMS].parent)
        raise CodebookError(f"{folder} already has codebook files; delete them to start over")
    dataset = dataset_by_name(project.config, dataset_name)
    fields = read_fields(dictionary) if dictionary else None
    items = template_items(project, dataset, read_data(project, dataset), fields)
    new = dict.fromkeys(
        row["instrument"]
        for row in items
        if row["instrument"] and row["instrument"] not in project.instruments
    )
    names = {f.form: f.form_label or redcap.form_name(f.form) for f in (fields or {}).values()}
    instruments = [{"instrument": i, "name": names.get(i, "")} for i in new]
    write_table(paths[ITEMS], ITEMS, items)
    write_table(paths[INSTRUMENTS], INSTRUMENTS, instruments)
    write_table(paths[SCORES], SCORES, [])
    return list(paths.values())


def read_fields(path: Path) -> dict[str, redcap.Field]:
    # A Qualtrics survey file or a REDCap data dictionary, told apart by extension.
    if path.suffix.lower() == ".qsf":
        return qualtrics.read_survey(path)
    return redcap.read_dictionary(path)


def template_items(
    project: Project,
    dataset: DatasetConfig,
    frame: pd.DataFrame,
    fields: dict[str, redcap.Field] | None = None,
) -> list[dict[str, str]]:
    config = project.config
    skipped = {id_column_for(config, dataset), dataset.group_column, dataset.date_column}
    mapped = {
        entry.column: (entry.instrument, entry.item)
        for entries in project.maps.values()
        for entry in entries
        if entry.instrument
    }
    # Longest first, so eps_10 wins over eps_1 for the column eps_10_w2.
    item_ids = sorted(
        (
            (item.id, instrument.id)
            for instrument in project.instruments.values()
            for item in instrument.items
        ),
        key=lambda pair: -len(pair[0]),
    )
    prefixes = Counter(prefix(column) for column in frame.columns if column not in skipped)
    missing = {str(code.code) for code in missing_codes_for(config, dataset)} | {""}
    field_names = sorted(fields or {}, key=len, reverse=True)
    rows = []
    for column in frame.columns:
        row = {"column": column, "instrument": "", "item": ""}
        if column not in skipped:
            known = known_item(column, mapped, item_ids)
            name = None if known else next((f for f in field_names if holds(column, f)), None)
            if known:
                row.update(instrument=known[0], item=known[1])
            elif name:
                field = fields[name]
                row.update(
                    instrument=field.form,
                    item=field.item,
                    text=field.text,
                    type=field.type,
                    choices=field.choices,
                    min=field.min,
                    max=field.max,
                )
            # Without a dictionary, columns sharing a prefix are a guess at a new instrument.
            elif fields is None and prefix(column) and prefixes[prefix(column)] > 1:
                row.update(instrument=prefix(column), item=column)
            if not known and not name and is_text(frame[column], missing):
                row["type"] = "text"
        rows.append(row)
    return rows


def known_item(
    column: str, mapped: dict[str, tuple[str, str]], item_ids: list[tuple[str, str]]
) -> tuple[str, str] | None:
    if column in mapped:
        return mapped[column]
    return next(
        ((instrument_id, item_id) for item_id, instrument_id in item_ids if holds(column, item_id)),
        None,
    )


def holds(column: str, item_id: str) -> bool:
    # eps_1 holds eps_1 and eps_1_w2, but not eps_10.
    return column == item_id or (column.startswith(item_id) and not column[len(item_id)].isalnum())


def prefix(column: str) -> str:
    found = re.match(r"[A-Za-z]+", column)
    return found.group().lower() if found else ""


def is_text(values: pd.Series, missing: set[str]) -> bool:
    answers = values[~values.isin(missing)]
    return bool(pd.to_numeric(answers, errors="coerce").isna().any())


def read_data(project: Project, dataset: DatasetConfig) -> pd.DataFrame:
    return get_source(dataset.source).read(dataset, project.root)


def write_table(path: Path, name: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The byte-order mark makes Excel open the file as UTF-8.
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(COLUMNS[name]))
        writer.writeheader()
        writer.writerows(rows)


def ai_prompt(project: Project, dataset_name: str) -> str:
    dataset = dataset_by_name(project.config, dataset_name)
    items = codebook_paths(project, dataset_name)[ITEMS].read_text(encoding="utf-8-sig").strip()
    guessed = {row.get("instrument") for row in csv.DictReader(io.StringIO(items))}
    known = [
        f"  - {instrument.id}: {instrument.name}"
        + (
            f" (items: {', '.join(item.id for item in instrument.items)})"
            if instrument.id in guessed
            else ""
        )
        for instrument in project.instruments.values()
    ]
    return PROMPT.format(
        dataset=dataset.name,
        study=dataset.study,
        wave=dataset.wave,
        reporter=dataset.reporter,
        format=format_text(),
        known="\n".join(known) or "  (none yet)",
        items=items,
    )


def format_text() -> str:
    parts = []
    for name, columns in COLUMNS.items():
        lines = [f"{name}, with the columns {', '.join(columns)}:"]
        lines.extend(f"- {column}: {meaning}" for column, meaning in columns.items())
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def split_ai_answer(project: Project, dataset_name: str, answer: str) -> list[Path]:
    blocks: dict[str, str] = {}
    for block in FENCE.findall(answer):
        text = block.strip()
        if text:
            name = table_name([cell.strip() for cell in next(csv.reader(io.StringIO(text)))])
            if name:
                blocks.setdefault(name, text)
    absent = [name for name in COLUMNS if name not in blocks]
    if absent:
        raise CodebookError(
            f"The answer has no code block for {', '.join(absent)}; "
            "ask the AI to answer with three csv code blocks."
        )
    paths = codebook_paths(project, dataset_name)
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(blocks[name] + "\n", encoding="utf-8-sig")
    return list(paths.values())


def table_name(header: list[str]) -> str | None:
    if "column" in header:
        return ITEMS
    if "score" in header:
        return SCORES
    if "name" in header:
        return INSTRUMENTS
    return None


def import_codebook(project: Project, dataset_name: str) -> ImportResult:
    return Importer(project, dataset_by_name(project.config, dataset_name)).run()


class Importer:
    def __init__(self, project: Project, dataset: DatasetConfig) -> None:
        self.project = project
        self.dataset = dataset
        self.folder = f"{defaults.CODEBOOK_DIR}/{dataset.name}"
        self.issues: list[Issue] = []
        self.map_rows: list[tuple[str, str, str]] = []
        self.drafts: dict[str, Draft] = {}
        self.score_columns: list[tuple[int, str, str]] = []

    def run(self) -> ImportResult:
        map_path = self.project.root / defaults.MAPS_DIR / f"{self.dataset.name}.csv"
        if map_path.exists():
            message = f"{self.dataset.name} already has a column map; importing would replace it"
            self.issues.append(
                Issue(
                    level="error",
                    code="codebook",
                    message=message,
                    location=relative(self.project, map_path),
                )
            )
            return ImportResult(self.issues)
        paths = codebook_paths(self.project, self.dataset.name)
        tables = {name: self.read_table(name, path) for name, path in paths.items()}
        if has_errors(self.issues):
            return ImportResult(self.issues)
        self.read_items(tables[ITEMS], set(read_data(self.project, self.dataset).columns))
        self.read_instruments(tables[INSTRUMENTS])
        self.read_scores(tables[SCORES])
        self.check_score_columns()
        if has_errors(self.issues):
            return ImportResult(self.issues)
        written = [self.write_instrument(draft) for draft in self.drafts.values()]
        written.append(self.write_map(map_path))
        used = dict.fromkeys(instrument for _, instrument, _ in self.map_rows if instrument)
        reused = [i for i in used if i in self.project.instruments]
        return ImportResult(self.issues, written, reused, self.steps(list(used)))

    def report(self, name: str, line: int | None, message: str, level: IssueLevel = "error"):
        location = f"{self.folder}/{name}" + (f":{line}" if line else "")
        self.issues.append(Issue(level=level, code="codebook", message=message, location=location))

    def read_table(self, name: str, path: Path) -> list[tuple[int, dict[str, str]]]:
        if is_placeholder(path):
            self.report(name, None, fetch_advice(path))
            return []
        if not path.is_file():
            self.report(name, None, "file not found; create the codebook files first")
            return []
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            self.report(name, None, "not UTF-8; in Excel save it as 'CSV UTF-8'")
            return []
        reader = csv.reader(io.StringIO(text))
        header = [cell.strip() for cell in next(reader, [])]
        absent = [column for column in COLUMNS[name] if column not in header]
        if absent:
            self.report(name, 1, f"the header is missing {', '.join(absent)}")
            return []
        rows = []
        for cells in reader:
            row = {
                column: cells[i].strip() if i < len(cells) else ""
                for i, column in enumerate(header)
            }
            if any(row.values()):
                rows.append((reader.line_num, row))
        return rows

    def read_items(self, rows: list[tuple[int, dict[str, str]]], columns: set[str]) -> None:
        seen_columns: dict[str, int] = {}
        seen_items: dict[tuple[str, str], int] = {}
        for line, row in rows:
            column, instrument_id, item_id = row["column"], row["instrument"], row["item"]
            if not column:
                self.report(ITEMS, line, "column is empty")
                continue
            if column in seen_columns:
                self.report(
                    ITEMS, line, f"column {column} is already on line {seen_columns[column]}"
                )
                continue
            seen_columns[column] = line
            if column not in columns:
                self.report(ITEMS, line, f"{column} is not a column of the data file")
                continue
            if bool(instrument_id) != bool(item_id):
                self.report(ITEMS, line, "instrument and item must be filled in together")
                continue
            self.map_rows.append((column, instrument_id, item_id))
            if not instrument_id:
                continue
            key = (instrument_id, item_id)
            if key in seen_items:
                message = f"{instrument_id} {item_id} is already on line {seen_items[key]}"
                self.report(ITEMS, line, message)
                continue
            seen_items[key] = line
            if item_id.startswith(defaults.SCORE_PREFIX):
                score_id = item_id.removeprefix(defaults.SCORE_PREFIX)
                self.score_columns.append((line, instrument_id, score_id))
            elif instrument_id in self.project.instruments:
                instrument = self.project.instruments[instrument_id]
                if item_id not in {item.id for item in instrument.items}:
                    self.report(ITEMS, line, f"{instrument_id} has no item {item_id}")
            else:
                self.add_item(line, instrument_id, item_id, row)

    def add_item(self, line: int, instrument_id: str, item_id: str, row: dict[str, str]) -> None:
        bad_ids = [
            f"{label} {value}"
            for label, value in (("instrument", instrument_id), ("item", item_id))
            if not ID_PATTERN.fullmatch(value)
        ]
        if bad_ids:
            self.report(
                ITEMS, line, f"{', '.join(bad_ids)}: use only letters, digits and underscores"
            )
            return
        messages: list[str] = []
        item_type = row["type"] or "choice"
        if item_type not in ITEM_TYPES:
            messages.append(f"type must be one of {', '.join(ITEM_TYPES)}")
        if not row["text"]:
            messages.append("text is empty")
        options = parse_choices(row["choices"], messages)
        if item_type == "choice" and not row["choices"]:
            messages.append("a choice item needs choices (or type number or text)")
        if item_type in ITEM_TYPES and item_type != "choice" and row["choices"]:
            messages.append(f"a {item_type} item has no choices")
        reverse = parse_flag(row["reverse"], messages)
        low, high = (parse_number(row[name], name, messages) for name in ("min", "max"))
        if item_type != "number" and (low is not None or high is not None):
            messages.append("min and max apply to number items only")
        if low is not None and high is not None and low > high:
            messages.append("min is above max")
        for message in messages:
            self.report(ITEMS, line, message)
        draft = self.drafts.setdefault(instrument_id, Draft(instrument_id, line))
        draft.items[item_id] = DraftItem(
            item_id, row["text"], item_type, options, reverse, low, high
        )

    def read_instruments(self, rows: list[tuple[int, dict[str, str]]]) -> None:
        seen: dict[str, int] = {}
        for line, row in rows:
            instrument_id = row["instrument"]
            if not instrument_id:
                self.report(INSTRUMENTS, line, "instrument is empty")
                continue
            if instrument_id in seen:
                message = f"{instrument_id} is already on line {seen[instrument_id]}"
                self.report(INSTRUMENTS, line, message)
                continue
            seen[instrument_id] = line
            if instrument_id in self.project.instruments:
                where = self.project.instrument_files[instrument_id]
                message = f"{instrument_id} is already in the project, so this row is ignored; edit {where} instead"
                self.report(INSTRUMENTS, line, message, "warning")
                continue
            draft = self.drafts.get(instrument_id)
            if draft is None:
                self.report(INSTRUMENTS, line, f"{instrument_id} has no items in {ITEMS}")
                continue
            if not row["name"]:
                self.report(INSTRUMENTS, line, "name is empty")
            draft.fields = row
        for draft in self.drafts.values():
            if draft.id not in seen:
                self.report(INSTRUMENTS, None, f"{draft.id} has no row; add one with its name")
            path = self.project.root / defaults.INSTRUMENTS_DIR / f"{draft.id}.yaml"
            if path.exists():
                message = f"{relative(self.project, path)} already exists with another id"
                self.report(ITEMS, draft.line, message)

    def read_scores(self, rows: list[tuple[int, dict[str, str]]]) -> None:
        seen: dict[tuple[str, str], int] = {}
        for line, row in rows:
            instrument_id, score_id = row["instrument"], row["score"]
            if instrument_id in self.project.instruments:
                where = self.project.instrument_files[instrument_id]
                message = f"{instrument_id} is already in the project, so this row is ignored; edit {where} instead"
                self.report(SCORES, line, message, "warning")
                continue
            draft = self.drafts.get(instrument_id)
            if draft is None:
                self.report(SCORES, line, f"no instrument {instrument_id} in {ITEMS}")
                continue
            messages: list[str] = []
            key = (instrument_id, score_id)
            if not ID_PATTERN.fullmatch(score_id):
                messages.append("score: use only letters, digits and underscores")
            elif key in seen:
                messages.append(f"{instrument_id} {score_id} is already on line {seen[key]}")
            seen[key] = line
            if not row["label"]:
                messages.append("label is empty")
            if row["method"] not in METHODS:
                messages.append(f"method must be {' or '.join(METHODS)}")
            if row["missing_rule"] and row["missing_rule"] not in MISSING_RULES:
                messages.append(f"missing_rule must be one of {', '.join(MISSING_RULES)}")
            items = score_items(draft, row["items"], messages)
            min_valid = parse_number(row["min_valid"], "min_valid", messages)
            if (
                items
                and min_valid is not None
                and not (isinstance(min_valid, int) and 1 <= min_valid <= len(items))
            ):
                messages.append(f"min_valid must be a whole number from 1 to {len(items)}")
            for message in messages:
                self.report(SCORES, line, message)
            score: dict[str, Any] = {
                "id": score_id,
                "label": row["label"],
                "method": row["method"],
                "items": items,
            }
            if row["missing_rule"]:
                score["missing_rule"] = row["missing_rule"]
            if min_valid is not None:
                score["min_valid"] = min_valid
            draft.scores.append(score)

    def check_score_columns(self) -> None:
        for line, instrument_id, score_id in self.score_columns:
            if instrument_id in self.project.instruments:
                ids = {score.id for score in self.project.instruments[instrument_id].scores}
            elif instrument_id in self.drafts:
                ids = {score["id"] for score in self.drafts[instrument_id].scores}
            else:
                self.report(ITEMS, line, f"no instrument {instrument_id} for this score column")
                continue
            if score_id not in ids:
                self.report(ITEMS, line, f"{instrument_id} has no score {score_id}")

    def write_instrument(self, draft: Draft) -> Path:
        path = self.project.root / defaults.INSTRUMENTS_DIR / f"{draft.id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(instrument_yaml(draft), encoding="utf-8", newline="\n")
        return path

    def write_map(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(MAP_COLUMNS)
            writer.writerows(self.map_rows)
        return path

    def steps(self, instrument_ids: list[str]) -> list[tuple[str, str]]:
        name, study = self.dataset.name, self.dataset.study
        content = self.project.studies.get(study)
        location = self.project.study_files.get(study, f"{defaults.STUDIES_DIR}/{study}.yaml")
        added, changed = [], []
        for instrument_id in instrument_ids:
            administration = (
                next((a for a in content.administrations if a.instrument == instrument_id), None)
                if content
                else None
            )
            if administration is None:
                added.append(f"  - {flow({'instrument': instrument_id, 'datasets': [name]})}")
            elif name not in administration.datasets:
                fields = administration.model_dump(exclude_defaults=True)
                fields["datasets"] = [*administration.datasets, name]
                changed.append(f"  - {flow(fields)}")
        if not (added or changed):
            return []
        if content is None:
            lines = [MODELINE.format("study"), dump({"study": study}), "administrations:", *added]
            return [(f"Create {location} with:", "\n".join(lines))]
        steps = []
        if added:
            steps.append((f"In {location}, add under administrations:", "\n".join(added)))
        if changed:
            steps.append(
                (f"In {location}, add {name} to these administrations:", "\n".join(changed))
            )
        return steps


def parse_choices(text: str, messages: list[str]) -> Options:
    options = []
    for part in filter(None, (p.strip() for p in text.split(";"))):
        value, sep, label = (s.strip() for s in part.partition("="))
        if not (sep and value and label):
            messages.append(f"choices: '{part}' should look like 1=Never")
            return ()
        options.append((number_or_text(value), label))
    values = [str(value) for value, _ in options]
    repeated = sorted({value for value in values if values.count(value) > 1})
    if repeated:
        messages.append(f"choices: {', '.join(repeated)} listed twice")
    return tuple(options)


def parse_flag(value: str, messages: list[str]) -> bool:
    if value.lower() in YES:
        return True
    if value.lower() not in NO:
        messages.append(f"reverse must be yes or no, not {value}")
    return False


def parse_number(value: str, name: str, messages: list[str]) -> Value | None:
    if not value:
        return None
    number = number_or_text(value)
    if isinstance(number, str):
        messages.append(f"{name} must be a number")
        return None
    return number


def number_or_text(value: str) -> Value:
    if INTEGER.fullmatch(value):
        return int(value)
    if DECIMAL.fullmatch(value):
        return float(value)
    return value


def score_items(draft: Draft, text: str, messages: list[str]) -> list[str]:
    order = list(draft.items)
    chosen: list[str] = []
    for part in filter(None, (p.strip() for p in text.split(";"))):
        first, sep, last = (s.strip() for s in part.partition("-"))
        if part in draft.items:
            chosen.append(part)
        elif sep and first in draft.items and last in draft.items:
            start, end = order.index(first), order.index(last)
            if start > end:
                messages.append(f"items: {part} runs backwards in {ITEMS} order")
            chosen.extend(order[start : end + 1])
        else:
            messages.append(f"items: {part} is not an item of {draft.id}")
    if not chosen and not messages:
        messages.append("items is empty")
    repeated = sorted({item_id for item_id in chosen if chosen.count(item_id) > 1})
    if repeated:
        messages.append(f"items: {', '.join(repeated)} listed twice")
    for item_id in dict.fromkeys(chosen):
        item = draft.items[item_id]
        if item.type != "choice":
            messages.append(f"items: {item_id} is a {item.type} item and cannot be scored")
        elif not all(isinstance(value, int | float) for value, _ in item.options):
            messages.append(f"items: {item_id} needs numeric choices to be scored")
    return chosen


def instrument_yaml(draft: Draft) -> str:
    sets = Counter(item.options for item in draft.items.values() if item.type == "choice")
    names = {options: f"set_{n}" for n, options in enumerate(sets, start=1)}
    # The most common set needs no mention on its items; ties go to the first one used.
    default = max(sets, key=lambda options: sets[options]) if sets else None
    fields = draft.fields
    document: dict[str, Any] = {"id": draft.id, "name": fields["name"]}
    for key, column in (
        ("abbreviation", "abbreviation"),
        ("kind", "kind"),
        ("construct_name", "construct"),
    ):
        if fields[column]:
            document[key] = fields[column]
    if sets:
        document["response_sets"] = [
            {
                "id": names[options],
                "options": [{"value": value, "label": label} for value, label in options],
            }
            for options in sets
        ]
        document["default_response_set"] = names[default]
    document["items"] = [item_fields(item, names, default) for item in draft.items.values()]
    if draft.scores:
        document["scores"] = draft.scores
    return yaml_text(document, "instrument")


def item_fields(item: DraftItem, names: dict[Options, str], default: Options | None) -> dict:
    fields: dict[str, Any] = {"id": item.id, "text": item.text}
    if item.type != "choice":
        fields["type"] = item.type
    elif item.options != default:
        fields["response_set"] = names[item.options]
    if item.min is not None:
        fields["min"] = item.min
    if item.max is not None:
        fields["max"] = item.max
    if item.reverse:
        fields["reverse"] = True
    return fields


def yaml_text(document: dict[str, Any], schema: str) -> str:
    # Matches the hand-written files: one line per item, score and option.
    lines = [MODELINE.format(schema)]
    for key, value in document.items():
        if not isinstance(value, list):
            lines.append(dump({key: value}))
            continue
        lines.append(f"{key}:")
        for element in value:
            if "options" in element:
                lines.append(f"  - {dump({'id': element['id']})}")
                lines.append("    options:")
                lines.extend(f"      - {flow(option)}" for option in element["options"])
            else:
                lines.append(f"  - {flow(element)}")
    return "\n".join(lines) + "\n"


def dump(value: dict[str, Any]) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=math.inf).rstrip("\n")


def flow(value: dict[str, Any]) -> str:
    text = yaml.safe_dump(
        value, default_flow_style=True, allow_unicode=True, sort_keys=False, width=math.inf
    )
    return text.rstrip("\n")


def relative(project: Project, path: Path) -> str:
    return path.relative_to(project.root).as_posix()
