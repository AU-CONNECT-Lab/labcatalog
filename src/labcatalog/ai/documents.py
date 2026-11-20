from dataclasses import dataclass, field
from pathlib import Path

from labcatalog.ai.scoring import pdf_text
from labcatalog.exceptions import LLMError
from labcatalog.llm import Image

SUFFIXES = (".pdf", ".docx")
FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
# Picture formats every provider takes; others are numbered in the text but not sent.
SENDABLE = ("image/png", "image/jpeg", "image/gif", "image/webp")
# Boxes to tick that Word draws from a symbol font.
SYMBOLS = {
    ("Wingdings", "F06F"): "☐",
    ("Wingdings", "F0A8"): "☐",
    ("Wingdings", "F0FE"): "☑",
    ("Wingdings", "F0FD"): "☒",
}


@dataclass
class Document:
    text: str
    # Each picture the text marks as [picture N] and a model can be sent, by its N.
    pictures: list[tuple[int, Image]] = field(default_factory=list)
    # The numbers of the pictures in a format no model takes, such as EMF.
    unsent: list[int] = field(default_factory=list)

    @property
    def marked(self) -> int:
        return len(self.pictures) + len(self.unsent)


def read_document(path: Path) -> Document:
    if path.suffix.lower() == ".docx":
        return word_document(path)
    return Document(pdf_text(path))


def word_document(path: Path) -> Document:
    # Paragraphs and tables in reading order, tables as markdown rows, pictures where they sit.
    from docx import Document as Word
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        word = Word(str(path))
    except Exception as err:
        raise LLMError(f"{path.name} cannot be read as a Word document: {err}") from err
    found = Document("")
    numbers: dict[str, int] = {}

    def picture(element) -> str:
        ids = [v for k, v in element.attrib.items() if k.endswith(("}embed", "}id"))]
        part = word.part.related_parts.get(ids[0]) if ids else None
        if part is None:
            return ""
        if str(part.partname) not in numbers:
            number = numbers[str(part.partname)] = found.marked + 1
            if part.content_type in SENDABLE:
                found.pictures.append((number, Image(part.content_type, part.blob)))
            else:
                found.unsent.append(number)
        return f"[picture {numbers[str(part.partname)]}]"

    def inside(element):
        # Word keeps a text box twice, as a drawing and as its VML fallback; read it once.
        for child in element:
            if child.tag != FALLBACK:
                yield child
                yield from inside(child)

    def text_of(paragraph: Paragraph) -> str:
        out = []
        for el in inside(paragraph._p):
            if el.tag == qn("w:t"):
                out.append(el.text or "")
            elif el.tag == qn("w:tab"):
                out.append("\t")
            elif el.tag in (qn("w:br"), qn("w:cr")):
                out.append(" / ")
            elif el.tag == qn("w:sym"):
                out.append(SYMBOLS.get((el.get(qn("w:font")), el.get(qn("w:char"))), ""))
            elif el.tag.endswith(("}blip", "}imagedata")):
                out.append(picture(el))
        return "".join(out).strip()

    def blocks(parent):
        # Content controls wrap paragraphs and tables, so their content counts as the parent's.
        for child in parent.iterchildren():
            if child.tag == qn("w:sdt"):
                yield from blocks(child.find(qn("w:sdtContent")))
            elif child.tag in (qn("w:p"), qn("w:tbl")):
                yield child

    def cell_text(tc) -> str:
        # A table inside a cell, often a grid of options, reads as the cell's text.
        texts = []
        for block in blocks(tc):
            if block.tag == qn("w:p"):
                texts.append(text_of(Paragraph(block, word)))
            else:
                inner = dict.fromkeys(c._tc for row in Table(block, word).rows for c in row.cells)
                texts += [cell_text(c) for c in inner]
        return " ".join(t for t in texts if t)

    lines = []
    for child in blocks(word.element.body):
        if child.tag == qn("w:p"):
            paragraph = Paragraph(child, word)
            text = text_of(paragraph)
            if text:
                style = paragraph.style.name if paragraph.style is not None else ""
                heading = (
                    "# " if style == "Heading 1" else "## " if style.startswith("Heading") else ""
                )
                lines.append(heading + text)
        else:
            lines.append("")
            for n, row in enumerate(Table(child, word).rows):
                seen, cells = set(), []
                for cell in row.cells:
                    # A merged cell repeats in each column it spans.
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(cell_text(cell._tc).replace("|", "/"))
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
                    if n == 0:
                        lines.append("|" + " --- |" * len(cells))
            lines.append("")
    found.text = "\n".join(lines).strip()
    return found
