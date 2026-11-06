import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from labcatalog.config import (
    DatasetConfig,
    ProjectConfig,
    dataset_by_name,
    id_column_for,
    missing_codes_for,
    roster_dataset,
    roster_name,
)
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
# The app's ink and muted grey; rules are a hex colour and a width in eighths of a point.
INK = RGBColor(0x1F, 0x1F, 0x21)
MUTED = RGBColor(0x6E, 0x6E, 0x73)
DARK_RULE = ("1F1F21", 8)
LIGHT_RULE = ("D8D8DA", 4)
NUMERIC = {"Rows", "People", "n", "M", "SD", "α", "ω"}
MARGIN = Cm(2.2)
LABEL_WIDTH = Cm(3.6)
THEME_FONTS = {
    "w:asciiTheme": "minorHAnsi",
    "w:hAnsiTheme": "minorHAnsi",
    "w:eastAsiaTheme": "minorEastAsia",
    "w:cstheme": "minorBidi",
}
# The elements Word expects after a paragraph's or a cell's borders, in schema order.
AFTER_BORDER = (
    "w:shd w:tabs w:suppressAutoHyphens w:kinsoku w:wordWrap w:overflowPunct "
    "w:topLinePunct w:autoSpaceDE w:autoSpaceDN w:bidi w:adjustRightInd w:snapToGrid "
    "w:spacing w:ind w:contextualSpacing w:mirrorIndents w:suppressOverlap w:jc "
    "w:textDirection w:textAlignment w:textboxTightWrap w:outlineLvl w:divId w:cnfStyle "
    "w:rPr w:sectPr w:pPrChange"
).split()
AFTER_CELL_BORDERS = (
    "w:shd w:noWrap w:tcMar w:textDirection w:tcFitText w:vAlign w:hideMark w:headers "
    "w:cellIns w:cellDel w:cellMerge w:tcPrChange"
).split()
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


@dataclass
class Caption:
    text: str


@dataclass
class Facts:
    rows: list[tuple[str, str]]


@dataclass
class Table:
    columns: list[str]
    rows: list[list[str]]


Block = Heading | Paragraph | Caption | Facts | Table


def codebook_docx(
    result: CatalogResult,
    plan: dict[str, list[str]],
    variables: list[dict],
    statistics: list[dict] | None,
    files: dict[str, str],
    studies: Sequence[str] = (),
) -> bytes:
    return rendered(codebook_blocks(result, plan, variables, statistics, files, studies))


def codebook_blocks(
    result: CatalogResult,
    plan: dict[str, list[str]],
    variables: list[dict],
    statistics: list[dict] | None,
    files: dict[str, str],
    studies: Sequence[str] = (),
) -> list[Block]:
    # The export's rows and files; studies are those whose participant roster is exported.
    config = result.project.config
    rostered = {s: config.studies[s].roster.instrument for s in studies}
    chosen = [
        i
        for i in result.project.instruments
        if any(i in ids for ids in plan.values()) or i in rostered.values()
    ]
    blocks = front(result, plan, studies, chosen)
    blocks += datasets_part(result, plan, studies, files)
    for instrument_id in chosen:
        given = [d for d, ids in plan.items() if instrument_id in ids]
        rosters = [s for s, i in rostered.items() if i == instrument_id]
        instrument = result.project.instruments[instrument_id]
        blocks += instrument_part(result, instrument, given, rosters)
        if statistics is not None:
            rows = [r for r in statistics if r["instrument"] == instrument_id]
            blocks += statistics_part(rows, config.stats.decimals)
    blocks += index_part([*plan, *(roster_name(s) for s in studies)], variables)
    return blocks


def front(
    result: CatalogResult, plan: dict[str, list[str]], rosters: Sequence[str], chosen: list[str]
) -> list[Block]:
    config = result.project.config
    counts = [count(len(plan), "dataset")] if plan else []
    counts += [count(len(rosters), "participant roster")] if rosters else []
    facts = [
        ("Contents", f"{', '.join(counts)} and {count(len(chosen), 'instrument')}"),
        ("Written", f"{date.today().isoformat()} by labcatalog {__version__}"),
    ]
    studies = dict.fromkeys([*(dataset_by_name(config, d).study for d in plan), *rosters])
    for study in studies:
        info = config.studies[study]
        facts.append((info.label or study, info.description or ""))
        if info.reference:
            facts.append(("Cite as", citation(result.project.bibliography, info.reference)))
        facts += lab_fields(config, "study", info)
    codes = shared_missing_codes(result, plan, rosters)
    if codes is not None:
        facts.append(
            ("Missing codes", f"{codes}. Blank cells are missing too." if codes else "Blank cells")
        )
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
        facts.append(("Groups", f"Each person's {group.name}{where} comes from {source}."))
    return [Heading(f"Codebook: {config.project.name}", 0), Facts(facts)]


def datasets_part(
    result: CatalogResult,
    plan: dict[str, list[str]],
    rosters: Sequence[str],
    files: dict[str, str],
) -> list[Block]:
    blocks: list[Block] = [Heading("Datasets", 1)]
    if plan:
        blocks += files_part({d: files[d] for d in plan if d in files})
        blocks.append(datasets_table(result, plan, rosters))
    if rosters:
        blocks.append(Caption("Participant rosters"))
        if files:
            blocks.append(Paragraph("Each roster is in a file of its own name."))
        blocks.append(rosters_table(result, rosters))
    return blocks


def datasets_table(
    result: CatalogResult, plan: dict[str, list[str]], rosters: Sequence[str]
) -> Table:
    config = result.project.config
    names = abbreviations(result)
    summaries = {s.dataset: s for s in result.summary.datasets}
    studies = {dataset_by_name(config, d).study for d in plan}
    by_dataset = shared_missing_codes(result, plan, rosters) is None
    steps = {name: made_by(result.project, name) for name in plan}
    stepped = any(steps.values())
    columns = ["Dataset", "Wave", "Reporter", "Collected", "Rows", "People", "Key columns"]
    columns += ["Instruments", *(["Missing codes"] if by_dataset else [])]
    columns += ["Made by"] if stepped else []
    labels, values = lab_columns(config, "dataset", [dataset_by_name(config, d) for d in plan])
    columns += labels
    rows = []
    for (name, instrument_ids), own in zip(plan.items(), values, strict=True):
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
                *([missing_text(config, dataset)] if by_dataset else []),
                *([steps[name]] if stepped else []),
                *own,
            ]
        )
    return Table(columns, rows)


def rosters_table(result: CatalogResult, rosters: Sequence[str]) -> Table:
    config = result.project.config
    rows = []
    for study in rosters:
        roster = config.studies[study].roster
        loaded = result.rosters[study]
        keys = [
            f"ID {loaded.id_column}",
            *([f"group {roster.group_column}"] if roster.group_column else []),
            *([f"role {roster.role_column}"] if roster.role_column else []),
        ]
        rows.append(
            [
                roster_name(study),
                config.studies[study].label or study,
                str(len(loaded.frame)),
                str(loaded.frame[loaded.id_column].nunique()),
                ", ".join(keys),
                abbreviations(result)[roster.instrument],
            ]
        )
    return Table(["Roster", "Study", "Rows", "People", "Key columns", "Instrument"], rows)


def files_part(files: dict[str, str]) -> list[Block]:
    if not files:
        return []
    if all(name == f"{dataset}.csv" for dataset, name in files.items()):
        first = next(iter(files.values()))
        return [Paragraph(f"Each dataset is in a file of its own name, such as {first}.")]
    table = next(iter(files.values()))
    return [Paragraph(f"The data are in {table}; each column starts with its dataset's name.")]


def instrument_part(
    result: CatalogResult, instrument: Instrument, given: list[str], rosters: list[str]
) -> list[Block]:
    config = result.project.config
    title = instrument.name
    if instrument.abbreviation:
        title += f" ({instrument.abbreviation})"
    blocks: list[Block] = [Heading(title, 1)]
    if instrument.description:
        blocks.append(Paragraph(instrument.description))
    modality = config.vocab.modality_labels.get(instrument.modality, instrument.modality)
    facts = [
        ("Construct", instrument.construct_name),
        ("Modality", modality),
        ("Instructions", joined(instrument.instructions) if instrument.instructions else None),
        *[
            ("Reference", citation(result.project.bibliography, r.key))
            for r in instrument.references
        ],
        ("License", instrument.license),
        ("Given in", given_text(result, instrument, given, rosters)),
        *lab_fields(config, "instrument", instrument),
    ]
    for content in result.project.studies.values():
        for administration in content.administrations:
            datasets = [d for d in administration.datasets if d in given]
            if administration.instrument != instrument.id or not datasets:
                continue
            for label, value in lab_fields(config, "administration", administration):
                facts.append((f"{label} ({', '.join(datasets)})", value))
    for response_set in instrument.response_sets:
        options = ", ".join(
            f"{o.value} = {o.label}" if o.label else str(o.value) for o in response_set.options
        )
        facts.append((f"Options ({response_set.id})", options))
    blocks.append(Facts([(label, value) for label, value in facts if value]))
    blocks += items_part(config, instrument)
    blocks += scores_part(config, instrument)
    blocks += differences_part(result, instrument, given)
    return blocks


def items_part(config: ProjectConfig, instrument: Instrument) -> list[Block]:
    if not instrument.items:
        return []
    answer = len(instrument.response_sets) > 1 or any(i.type != "choice" for i in instrument.items)
    reverse = any(i.reverse for i in instrument.items)
    columns = ["Item", "Text", *(["Answer"] if answer else []), *(["Reverse"] if reverse else [])]
    labels, values = lab_columns(config, "item", instrument.items)
    rows = []
    for item, own in zip(instrument.items, values, strict=True):
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
                *own,
            ]
        )
    return [Caption("Items"), Table(columns + labels, rows)]


def scores_part(config: ProjectConfig, instrument: Instrument) -> list[Block]:
    if not instrument.scores:
        return []
    labels, values = lab_columns(config, "score", instrument.scores)
    rows = []
    for score, own in zip(instrument.scores, values, strict=True):
        if score.method == SCRIPT:
            rows.append([score.id, score.label, "computed by a script", "", "", *own])
            continue
        missing = MISSING_RULES[score.missing_rule]
        if score.min_valid is not None:
            missing += f", at least {score.min_valid} answered"
        rows.append([score.id, score.label, score.method, ", ".join(score.items), missing, *own])
    return [
        Caption("Scores"),
        Table(["Score", "Label", "Method", "Items", "Scored", *labels], rows),
    ]


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
    return [Caption("Differences between datasets"), Table(["Dataset", "Difference"], rows)]


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
    return [Caption("Statistics"), Table(columns, table)]


def index_part(datasets: list[str], variables: list[dict]) -> list[Block]:
    blocks: list[Block] = [
        Heading("Variables", 1),
        Paragraph("Every column of the data files by dataset, as variables.csv lists them."),
    ]
    for dataset in datasets:
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


def shared_missing_codes(
    result: CatalogResult, plan: dict[str, list[str]], rosters: Sequence[str]
) -> str | None:
    # One sentence when every file has the same codes; None sends them to the datasets table.
    config = result.project.config
    datasets = [dataset_by_name(config, d) for d in plan]
    datasets += [roster_dataset(config, s) for s in rosters]
    found = {missing_text(config, d) for d in datasets}
    return found.pop() if len(found) == 1 else None


def missing_text(config: ProjectConfig, dataset: DatasetConfig) -> str:
    codes = missing_codes_for(config, dataset)
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


def given_text(
    result: CatalogResult, instrument: Instrument, given: list[str], rosters: list[str]
) -> str:
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
    parts = [
        ", ".join(names) + (f" (about: {target})" if target else "")
        for target, names in targets.items()
    ]
    parts += [f"the participant roster ({roster_name(s)})" for s in rosters]
    return "; ".join(parts)


def lab_fields(config: ProjectConfig, applies_to: str, owner) -> list[tuple[str, str]]:
    # The lab's own declared fields this study, instrument or administration fills in.
    return [
        (field.label or field.name, field_text(owner.custom[field.name]))
        for field in config.custom_fields
        if field.applies_to == applies_to and field.name in owner.custom
    ]


def lab_columns(
    config: ProjectConfig, applies_to: str, owners: Sequence
) -> tuple[list[str], list[list[str]]]:
    # A column for each of the lab's own fields that any of these rows fills in.
    fields = [
        field
        for field in config.custom_fields
        if field.applies_to == applies_to and any(field.name in o.custom for o in owners)
    ]
    labels = [field.label or field.name for field in fields]
    values = [[field_text(o.custom.get(field.name)) for field in fields] for o in owners]
    return labels, values


def field_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def abbreviations(result: CatalogResult) -> dict[str, str]:
    return {i: s.abbreviation or i for i, s in result.project.instruments.items()}


def joined(text: str | dict[str, str]) -> str:
    return " / ".join(as_text_dict(text).values())


def count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def rendered(blocks: list[Block]) -> bytes:
    document = Document()
    styled(document)
    footer(document, blocks[0].text)
    for block in blocks:
        if isinstance(block, Heading):
            document.add_heading(block.text, block.level)
        elif isinstance(block, Facts):
            add_facts(document, block)
        elif isinstance(block, Table):
            add_table(document, block)
        elif isinstance(block, Caption):
            caption = document.add_paragraph()
            caption.add_run(block.text).bold = True
            caption.paragraph_format.space_before = Pt(8)
            caption.paragraph_format.space_after = Pt(3)
            caption.paragraph_format.keep_with_next = True
        else:
            document.add_paragraph(block.text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def styled(document) -> None:
    section = document.sections[0]
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, MARGIN)
    normal = document.styles["Normal"]
    normal.font.size = Pt(10)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(4)
    sizes = {"Title": Pt(18), "Heading 1": Pt(13), "Heading 2": Pt(11)}
    for name, size in sizes.items():
        style = document.styles[name]
        style.font.size = size
        style.font.bold = True
        style.font.color.rgb = INK
        # The template sets headings in its display font; the body's reads as one document.
        fonts = style.element.rPr.find(qn("w:rFonts"))
        for attribute, theme in THEME_FONTS.items():
            fonts.set(qn(attribute), theme)
    document.styles["Title"].paragraph_format.space_after = Pt(10)
    underline(document.styles["Title"], DARK_RULE)
    heading = document.styles["Heading 1"]
    heading.paragraph_format.space_before = Pt(18)
    heading.paragraph_format.space_after = Pt(6)
    underline(heading, LIGHT_RULE)
    document.styles["Heading 2"].paragraph_format.space_before = Pt(12)
    document.styles["Heading 2"].paragraph_format.space_after = Pt(4)


def underline(style, rule: tuple[str, int]) -> None:
    properties = style.element.get_or_add_pPr()
    old = properties.find(qn("w:pBdr"))
    if old is not None:
        properties.remove(old)
    border = OxmlElement("w:pBdr")
    border.append(edge("bottom", rule, space=2))
    properties.insert_element_before(border, *AFTER_BORDER)


def footer(document, title: str) -> None:
    section = document.sections[0]
    paragraph = section.footer.paragraphs[0]
    width = section.page_width - section.left_margin - section.right_margin
    paragraph.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
    run = paragraph.add_run(f"{title}\t")
    run.font.size = Pt(8)
    run.font.color.rgb = MUTED
    page = OxmlElement("w:fldSimple")
    page.set(qn("w:instr"), "PAGE")
    shown = paragraph.add_run("1")
    shown.font.size = Pt(8)
    shown.font.color.rgb = MUTED
    paragraph._p.remove(shown._r)
    page.append(shown._r)
    paragraph._p.append(page)


def add_facts(document, facts: Facts) -> None:
    section = document.sections[0]
    width = section.page_width - section.left_margin - section.right_margin
    grid = document.add_table(rows=0, cols=2)
    grid.autofit = False
    for label, value in facts.rows:
        left, right = grid.add_row().cells
        put(left, label, size=Pt(9), color=MUTED)
        put(right, value)
    for column, size in zip(grid.columns, (LABEL_WIDTH, width - LABEL_WIDTH), strict=True):
        column.width = size
        for cell in column.cells:
            cell.width = size
    spacer(document)


def add_table(document, table: Table) -> None:
    grid = document.add_table(rows=1, cols=len(table.columns))
    grid._tbl.tblPr.find(qn("w:tblW")).set(qn("w:type"), "pct")
    grid._tbl.tblPr.find(qn("w:tblW")).set(qn("w:w"), "5000")
    numeric = [label in NUMERIC for label in table.columns]
    for cell, label, right in zip(grid.rows[0].cells, table.columns, numeric, strict=True):
        put(cell, label, bold=True, size=Pt(9), right=right)
        bordered(cell, top=DARK_RULE, bottom=DARK_RULE)
    # The header row repeats on each page a long table runs over.
    rows(grid.rows[0], "w:cantSplit", "w:tblHeader")
    for n, values in enumerate(table.rows, start=1):
        row = grid.add_row()
        rows(row, "w:cantSplit")
        below = DARK_RULE if n == len(table.rows) else LIGHT_RULE
        for cell, value, right in zip(row.cells, values, numeric, strict=True):
            put(cell, value, size=Pt(9), right=right)
            bordered(cell, bottom=below)
    spacer(document)


def put(cell, text: str, bold: bool = False, size=None, color=None, right: bool = False) -> None:
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(1)
    if right:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run(text)
    run.bold = bold or None
    run.font.size = size
    if color is not None:
        run.font.color.rgb = color


def bordered(cell, **rules: tuple[str, int]) -> None:
    borders = OxmlElement("w:tcBorders")
    for side, rule in rules.items():
        borders.append(edge(side, rule))
    cell._tc.get_or_add_tcPr().insert_element_before(borders, *AFTER_CELL_BORDERS)


def edge(side: str, rule: tuple[str, int], space: int = 0):
    color, size = rule
    found = OxmlElement(f"w:{side}")
    for key, value in (("val", "single"), ("sz", str(size)), ("space", str(space))):
        found.set(qn(f"w:{key}"), value)
    found.set(qn("w:color"), color)
    return found


def rows(row, *marks: str) -> None:
    properties = row._tr.get_or_add_trPr()
    for mark in marks:
        properties.append(OxmlElement(mark))


def spacer(document) -> None:
    gap = document.add_paragraph()
    gap.paragraph_format.space_after = Pt(0)
    gap.paragraph_format.line_spacing = Pt(8)
