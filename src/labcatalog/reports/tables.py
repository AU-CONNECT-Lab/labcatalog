import html as markup
import io
import re
from dataclasses import dataclass

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

# A placeholder the author replaces with the table's number in the paper.
LABEL = "Table X"
# Statistical symbols that APA style sets in italics, in headers and notes.
SYMBOLS = re.compile(r"(?<!\w)(n|N|M|SD|SE|r|p|t|F|df|d|R²|η²)(?!\w)")
TEX = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"$<$",
    ">": r"$>$",
    "α": r"$\alpha$",
    "η": r"$\eta$",
    "χ": r"$\chi$",
    "ω": r"$\omega$",
    "Δ": r"$\Delta$",
    "²": r"\textsuperscript{2}",
    "·": r"$\cdot$",
    "−": r"$-$",
    " ": "~",
}


@dataclass
class PaperTable:
    title: str
    columns: list[dict]
    rows: list[dict]
    note: str = ""


def segments(text: str) -> list[tuple[str, bool]]:
    # Splitting on a capturing group alternates plain text and symbols.
    return [(part, i % 2 == 1) for i, part in enumerate(SYMBOLS.split(text)) if part]


def cell(row: dict, column: dict) -> str:
    value = row.get(column["name"])
    return "" if value is None else str(value)


def centered(column: dict) -> bool:
    return column.get("align") != "left"


def html(table: PaperTable, page: bool = False) -> str:
    line = f"1px solid {'currentColor' if page else 'black'}"
    pad = "padding:2px 10px;"

    def rich(text: str) -> str:
        return "".join(
            f"<i>{markup.escape(part)}</i>" if italic else markup.escape(part)
            for part, italic in segments(text)
        )

    def align(column: dict) -> str:
        return f"text-align:{'center' if centered(column) else 'left'};"

    head = "".join(
        f'<th style="{pad}{align(c)}font-weight:normal;border-top:{line};border-bottom:{line}">'
        f"{rich(c['label'])}</th>"
        for c in table.columns
    )
    body = []
    for i, row in enumerate(table.rows):
        last = f"border-bottom:{line};" if i == len(table.rows) - 1 else ""
        cells = "".join(
            f'<td style="{pad}{align(c)}{last}">{markup.escape(cell(row, c))}</td>'
            for c in table.columns
        )
        body.append(f"<tr>{cells}</tr>")
    parts = [] if page else [f'<p style="margin:0"><b>{LABEL}</b></p>']
    parts += [
        f'<p style="margin:0 0 6px"><i>{markup.escape(table.title)}</i></p>',
        f'<table style="border-collapse:collapse"><thead><tr>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>",
    ]
    if table.note:
        parts.append(f'<p style="margin:6px 0 0"><i>Note.</i> {rich(table.note)}</p>')
    return "".join(parts)


def plain(table: PaperTable) -> str:
    lines = [LABEL, table.title, "\t".join(c["label"] for c in table.columns)]
    lines += ["\t".join(cell(row, c) for c in table.columns) for row in table.rows]
    if table.note:
        lines.append(f"Note. {table.note}")
    return "\n".join(lines)


def tex(text: str) -> str:
    return "".join(TEX.get(ch, ch) for ch in text)


def latex(table: PaperTable) -> str:
    def rich(text: str) -> str:
        return "".join(
            rf"\textit{{{tex(part)}}}" if italic else tex(part) for part, italic in segments(text)
        )

    spec = "".join("c" if centered(c) else "l" for c in table.columns)
    lines = [
        r"% Needs \usepackage{booktabs}",
        r"\begin{table}",
        rf"\caption{{{tex(table.title)}}}",
        rf"\begin{{tabular}}{{{spec}}}",
        r"\toprule",
        " & ".join(rich(c["label"]) for c in table.columns) + r" \\",
        r"\midrule",
        *[" & ".join(tex(cell(row, c)) for c in table.columns) + r" \\" for row in table.rows],
        r"\bottomrule",
        r"\end{tabular}",
    ]
    if table.note:
        lines.append(rf"\par\smallskip\textit{{Note.}} {rich(table.note)}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


def docx(table: PaperTable) -> bytes:
    document = Document()
    document.add_paragraph().add_run(LABEL).bold = True
    document.add_paragraph().add_run(table.title).italic = True
    grid = document.add_table(rows=len(table.rows) + 1, cols=len(table.columns))
    for j, column in enumerate(table.columns):
        target = grid.cell(0, j)
        add_runs(target.paragraphs[0], column["label"])
        rules(target, "top", "bottom")
    for i, row in enumerate(table.rows, start=1):
        for j, column in enumerate(table.columns):
            target = grid.cell(i, j)
            target.paragraphs[0].add_run(cell(row, column))
            if i == len(table.rows):
                rules(target, "bottom")
    for row in grid.rows:
        for column, target in zip(table.columns, row.cells, strict=True):
            if centered(column):
                target.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    if table.note:
        paragraph = document.add_paragraph()
        paragraph.add_run("Note.").italic = True
        add_runs(paragraph, f" {table.note}")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def add_runs(paragraph: Paragraph, text: str) -> None:
    for part, italic in segments(text):
        paragraph.add_run(part).italic = italic


def rules(target, *sides: str) -> None:
    borders = OxmlElement("w:tcBorders")
    for side in sides:
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), "4")
        edge.set(qn("w:color"), "000000")
        borders.append(edge)
    target._tc.get_or_add_tcPr().append(borders)


def csv(table: PaperTable) -> bytes:
    frame = pd.DataFrame(table.rows, columns=[c["name"] for c in table.columns])
    frame.columns = [c["label"] for c in table.columns]
    # The byte order mark lets Excel read the file as UTF-8.
    return ("﻿" + frame.to_csv(index=False)).encode("utf-8")


def files(name: str, table: PaperTable) -> dict[str, bytes]:
    return {
        f"{name}.csv": csv(table),
        f"{name}.docx": docx(table),
        f"{name}.tex": latex(table).encode("utf-8"),
    }
