import io
import math
from dataclasses import dataclass
from datetime import date

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from labcatalog.config import dataset_by_name, id_column_for, missing_codes_for
from labcatalog.data.resolve import as_text_dict
from labcatalog.metadata.bibliography import citation
from labcatalog.metadata.scripts import language_of
from labcatalog.metadata.validate import same_file
from labcatalog.pipeline import CatalogResult
from labcatalog.project import Project
from labcatalog.reports.results import bounded, number
from labcatalog.schema import SCRIPT, Instrument
from labcatalog.version import __version__

CODEBOOK = "codebook.docx"
MISSING_RULES = {
    "complete": "only when every item is answered",
    "prorate": "from the answered items",
    "zero": "missing items count as 0",
}


@dataclass
class Heading:
    text: str
    level: int


@dataclass
class Paragraph:
    text: str
    label: str = ""


@dataclass
class Table:
    columns: list[str]
    rows: list[list[str]]


Block = Heading | Paragraph | Table


def codebook_docx(
    result: CatalogResult,
    plan: dict[str, list[str]],
    variables: list[dict],
    statistics: list[dict] | None,
    files: dict[str, str],
) -> bytes:
    return rendered(codebook_blocks(result, plan, variables, statistics, files))


def codebook_blocks(
    result: CatalogResult,
    plan: dict[str, list[str]],
    variables: list[dict],
    statistics: list[dict] | None,
    files: dict[str, str],
) -> list[Block]:
    # variables and statistics are the export's rows; files maps each dataset to its data file.
    chosen = [i for i in result.project.instruments if any(i in ids for ids in plan.values())]
    blocks = front(result, plan, chosen)
    blocks += datasets_part(result, plan, files)
    for instrument_id in chosen:
        given = [d for d, ids in plan.items() if instrument_id in ids]
        blocks += instrument_part(result, result.project.instruments[instrument_id], given)
        if statistics is not None:
            rows = [r for r in statistics if r["instrument"] == instrument_id]
            blocks += statistics_part(rows, result.project.config.stats.decimals)
    blocks += index_part(plan, variables)
    return blocks


def front(result: CatalogResult, plan: dict[str, list[str]], chosen: list[str]) -> list[Block]:
    config = result.project.config
    blocks: list[Block] = [
        Heading(f"Codebook: {config.project.name}", 0),
        Paragraph(
            f"Written by labcatalog {__version__} on {date.today().isoformat()}: "
            f"{count(len(plan), 'dataset')} and {count(len(chosen), 'instrument')}."
        ),
    ]
    studies = dict.fromkeys(dataset_by_name(config, d).study for d in plan)
    for study in studies:
        info = config.studies[study]
        blocks.append(Paragraph(info.description or "", label=f"{info.label or study}. "))
        if info.reference:
            blocks.append(
                Paragraph(citation(result.project.bibliography, info.reference), "Cite as: ")
            )
    codes = shared_missing_codes(result, plan)
    if codes is not None:
        said = f"{codes}. Blank cells are missing too." if codes else "Only blank cells."
        blocks.append(Paragraph(said, "Missing codes: "))
    group = config.ids.group
    for study in studies:
        roster = config.studies[study].roster
        if group and roster and roster.group_column:
            source = f"the {roster.group_column} column of the participant roster, {roster.path}"
        elif group and group.from_id:
            source = f"the ID, by the pattern {group.from_id}"
        else:
            continue
        where = f" in {config.studies[study].label or study}" if len(studies) > 1 else ""
        blocks.append(Paragraph(f"Each person's {group.name}{where} comes from {source}."))
    return blocks


def datasets_part(
    result: CatalogResult, plan: dict[str, list[str]], files: dict[str, str]
) -> list[Block]:
    config = result.project.config
    names = {i: s.abbreviation or i for i, s in result.project.instruments.items()}
    summaries = {s.dataset: s for s in result.summary.datasets}
    studies = {dataset_by_name(config, d).study for d in plan}
    by_dataset = shared_missing_codes(result, plan) is None
    steps = {name: made_by(result.project, name) for name in plan}
    stepped = any(steps.values())
    columns = ["Dataset", "Wave", "Reporter", "Collected", "Rows", "People", "Key columns"]
    columns += ["Instruments", *(["Missing codes"] if by_dataset else [])]
    columns += ["Made by"] if stepped else []
    rows = []
    for name, instrument_ids in plan.items():
        dataset = dataset_by_name(config, name)
        summary = summaries[name]
        wave = f"Wave {dataset.wave}"
        if len(studies) > 1:
            wave = f"{config.studies[dataset.study].label or dataset.study} {wave.lower()}"
        dates = [d.isoformat() for d in (summary.first_date, summary.last_date) if d]
        keys = [
            f"ID {id_column_for(config, dataset)}",
            *([f"filled in by {dataset.respondent_column}"] if dataset.respondent_column else []),
            *([f"date {dataset.date_column}"] if dataset.date_column else []),
        ]
        rows.append(
            [
                name,
                wave,
                dataset.reporter,
                " to ".join(dict.fromkeys(dates)),
                str(summary.n_rows),
                str(summary.n_ids),
                ", ".join(keys),
                ", ".join(names[i] for i in instrument_ids),
                *([missing_text(result, name)] if by_dataset else []),
                *([steps[name]] if stepped else []),
            ]
        )
    return [Heading("Datasets", 1), *files_part(files), Table(columns, rows)]


def files_part(files: dict[str, str]) -> list[Block]:
    if not files:
        return []
    written = list(dict.fromkeys(files.values()))
    if len(written) == len(files):
        return [Paragraph(f"Each dataset is in a file of its own name, such as {written[0]}.")]
    return [
        Paragraph(f"All of them are in {written[0]}; each column starts with its dataset's name.")
    ]


def instrument_part(result: CatalogResult, instrument: Instrument, given: list[str]) -> list[Block]:
    config = result.project.config
    title = instrument.name
    if instrument.abbreviation:
        title += f" ({instrument.abbreviation})"
    blocks: list[Block] = [Heading(title, 1)]
    if instrument.description:
        blocks.append(Paragraph(instrument.description))
    modality = config.vocab.modality_labels.get(instrument.modality, instrument.modality)
    facts = [
        ("Construct: ", instrument.construct_name),
        ("Modality: ", modality),
        ("Instructions: ", joined(instrument.instructions) if instrument.instructions else None),
        *[
            ("Reference: ", citation(result.project.bibliography, r.key))
            for r in instrument.references
        ],
        ("License: ", instrument.license),
        ("Given in: ", given_text(result, instrument, given)),
    ]
    blocks += [Paragraph(text, label) for label, text in facts if text]
    for response_set in instrument.response_sets:
        options = ", ".join(
            f"{o.value} = {o.label}" if o.label else str(o.value) for o in response_set.options
        )
        blocks.append(Paragraph(options, f"Options {response_set.id}: "))
    blocks += items_part(instrument)
    blocks += scores_part(instrument)
    blocks += differences_part(result, instrument, given)
    return blocks


def items_part(instrument: Instrument) -> list[Block]:
    if not instrument.items:
        return []
    answer = len(instrument.response_sets) > 1 or any(i.type != "choice" for i in instrument.items)
    reverse = any(i.reverse for i in instrument.items)
    columns = ["Item", "Text", *(["Answer"] if answer else []), *(["Reverse"] if reverse else [])]
    rows = []
    for item in instrument.items:
        if item.type == "choice":
            kind = item.response_set or instrument.default_response_set or ""
        elif item.type == "number":
            bounds = " to ".join(f"{v:g}" for v in (item.min, item.max) if v is not None)
            kind = f"number {bounds}".strip()
        else:
            kind = "open answer, not in the data files"
        rows.append(
            [
                item.id,
                joined(item.text),
                *([kind] if answer else []),
                *(["yes" if item.reverse else ""] if reverse else []),
            ]
        )
    return [Table(columns, rows)]


def scores_part(instrument: Instrument) -> list[Block]:
    rows = []
    for score in instrument.scores:
        if score.method == SCRIPT:
            rows.append([score.id, score.label, "computed by a script", "", ""])
            continue
        missing = MISSING_RULES[score.missing_rule]
        if score.min_valid is not None:
            missing += f", at least {score.min_valid} answered"
        rows.append([score.id, score.label, score.method, ", ".join(score.items), missing])
    if not rows:
        return []
    return [Table(["Score", "Label", "Method", "Items", "Scored"], rows)]


def differences_part(
    result: CatalogResult, instrument: Instrument, given: list[str]
) -> list[Block]:
    rows = []
    for dataset in given:
        found = {
            v.item_id: v
            for v in result.catalog.variables_for(dataset)
            if v.instrument_id == instrument.id
        }
        notes = []
        absent = [i.id for i in instrument.items if i.id not in found]
        if absent:
            notes.append(f"not in the data: {', '.join(absent)}")
        for item in instrument.items:
            variable = found.get(item.id)
            if variable is None:
                continue
            if variable.text != as_text_dict(item.text):
                notes.append(f'{item.id} reads "{joined(variable.text)}"')
            usual = item.response_set or instrument.default_response_set
            if item.type == "choice" and variable.response_set != usual:
                notes.append(f"{item.id} has options {variable.response_set}")
        if any(v.reversed_in_data and v.reverse for v in found.values()):
            notes.append("reversed items are already reversed in the data")
        if notes:
            rows.append([dataset, "; ".join(notes)])
    if not rows:
        return []
    return [Paragraph("", "Differences between datasets"), Table(["Dataset", "Difference"], rows)]


def statistics_part(rows: list[dict], digits: int) -> list[Block]:
    if not rows:
        return []
    omega = any(r["omega"] != "" for r in rows)
    columns = ["Dataset", "Score", "n", "M", "SD", "α", *(["ω"] if omega else [])]

    def shown(value: float | None, show=number) -> str:
        return "" if value is None or math.isnan(value) else show(value, digits)

    table = [
        [
            r["dataset"],
            r["label"],
            str(r["n"]),
            shown(r["mean"]),
            shown(r["sd"]),
            shown(r["alpha"], bounded),
            *([shown(r["omega"] if r["omega"] != "" else None, bounded)] if omega else []),
        ]
        for r in rows
    ]
    return [Paragraph("", "Statistics"), Table(columns, table)]


def index_part(plan: dict[str, list[str]], variables: list[dict]) -> list[Block]:
    blocks: list[Block] = [
        Heading("Variables", 1),
        Paragraph("Every column of the data files by dataset, as variables.csv lists them."),
    ]
    for dataset in plan:
        rows = [
            [
                r["column"],
                r["abbreviation"] or r["instrument"],
                r["item"],
                f"score, {r['type']}"
                if r["kind"] == "score"
                else ("open answer, not exported" if r["type"] == "text" else r["type"]),
            ]
            for r in variables
            if r["dataset"] == dataset
        ]
        blocks += [
            Heading(dataset, 2),
            Table(["Column", "Instrument", "Item or score", "Type"], rows),
        ]
    return blocks


def shared_missing_codes(result: CatalogResult, plan: dict[str, list[str]]) -> str | None:
    # One sentence when every dataset has the same codes; None sends them to the datasets table.
    found = {missing_text(result, d) for d in plan}
    return found.pop() if len(found) == 1 else None


def missing_text(result: CatalogResult, dataset: str) -> str:
    config = result.project.config
    codes = missing_codes_for(config, dataset_by_name(config, dataset))
    # Blank cells are always missing, so a code for them is said once on its own.
    return "; ".join(f"{c.code} = {c.label}" for c in codes if str(c.code) != "")


def made_by(project: Project, dataset: str) -> str:
    path = dataset_by_name(project.config, dataset).path
    if path is None:
        return ""
    target = same_file(project, path)
    steps = []
    for step in project.config.prepare:
        if target in {same_file(project, p) for p in step.outputs}:
            script = next((p for p in step.inputs if language_of(p)), None)
            steps.append(f"{step.name} ({script})" if script else step.name)
    return ", ".join(steps)


def given_text(result: CatalogResult, instrument: Instrument, given: list[str]) -> str:
    targets: dict[str, list[str]] = {}
    for dataset in given:
        target = next(
            (
                v.target
                for v in result.catalog.variables_for(dataset)
                if v.instrument_id == instrument.id
            ),
            None,
        )
        targets.setdefault(target or "", []).append(dataset)
    return "; ".join(
        ", ".join(names) + (f" (about: {target})" if target else "")
        for target, names in targets.items()
    )


def joined(text: str | dict[str, str]) -> str:
    return " / ".join(as_text_dict(text).values())


def count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def rendered(blocks: list[Block]) -> bytes:
    document = Document()
    # Small enough for the datasets table's columns to fit a portrait page.
    document.styles["Normal"].font.size = Pt(10)
    for block in blocks:
        if isinstance(block, Heading):
            document.add_heading(block.text, block.level)
        elif isinstance(block, Paragraph):
            paragraph = document.add_paragraph()
            if block.label:
                paragraph.add_run(block.label).bold = True
            paragraph.add_run(block.text)
        else:
            add_table(document, block)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def add_table(document, table: Table) -> None:
    grid = document.add_table(rows=1, cols=len(table.columns))
    grid.style = "Table Grid"
    head = grid.rows[0]
    for cell, label in zip(head.cells, table.columns, strict=True):
        cell.paragraphs[0].add_run(label).bold = True
    # The header row repeats on each page a long table runs over.
    marker = OxmlElement("w:tblHeader")
    marker.set(qn("w:val"), "true")
    head._tr.get_or_add_trPr().append(marker)
    for row in table.rows:
        for cell, value in zip(grid.add_row().cells, row, strict=True):
            cell.text = value
    document.add_paragraph()
