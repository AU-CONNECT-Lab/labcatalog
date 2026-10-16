import json
import re
from collections import Counter
from pathlib import Path

from labcatalog.codebook.redcap import Field, plain
from labcatalog.exceptions import CodebookError

SINGLE = {"SAVR", "SAHR", "SACOL", "DL", "SB", "NPS"}
MULTIPLE = {"MAVR", "MAHR", "MACOL", "MSB"}
SELECTED = "1=Selected"


def read_survey(path: Path) -> dict[str, Field]:
    try:
        survey = json.loads(path.read_text(encoding="utf-8-sig"))
        elements = survey["SurveyElements"]
    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
        raise CodebookError(f"{path.name} is not a Qualtrics survey file (.qsf)") from None
    questions = {e["PrimaryAttribute"]: e["Payload"] for e in elements if e["Element"] == "SQ"}
    found: list[tuple[str, Field]] = []
    for block in blocks(elements):
        label = (block.get("Description") or "").strip()
        form = slug(label) or "block"
        for entry in block.get("BlockElements") or []:
            question = questions.get(entry.get("QuestionID"))
            if entry.get("Type") == "Question" and question:
                found += columns_of(question, form, label)
    # A column name that two questions share cannot be told apart, so a person fills it in.
    counts = Counter(column for column, _ in found)
    return {column: field for column, field in found if counts[column] == 1}


def blocks(elements: list[dict]) -> list[dict]:
    payload = next((e["Payload"] for e in elements if e["Element"] == "BL"), [])
    listed = payload.values() if isinstance(payload, dict) else payload
    return [b for b in listed if b.get("Type") != "Trash"]


def columns_of(question: dict, form: str, label: str) -> list[tuple[str, Field]]:
    # Export column names to what they hold, as Qualtrics names them in a CSV export.
    tag = question.get("DataExportTag") or ""
    kind, selector = question.get("QuestionType"), question.get("Selector")
    text = plain(question.get("QuestionText") or "")
    choices = ordered(question.get("Choices"), question.get("ChoiceOrder"))
    recode = question.get("RecodeValues") or {}

    def field(column: str, item_text: str, item_type: str, **rest: str) -> tuple[str, Field]:
        return column, Field(item_id(column), form, item_text, item_type, form_label=label, **rest)

    if not tag:
        return []
    if kind == "MC" and selector in SINGLE:
        options = "; ".join(f"{code(recode, cid)}={display(c)}" for cid, c in choices)
        return [field(tag, text, "choice", choices=options), *entries(tag, choices, recode, field)]
    if kind == "MC" and selector in MULTIPLE:
        return [
            field(f"{tag}_{code(recode, cid)}", f"{text}: {display(c)}", "choice", choices=SELECTED)
            for cid, c in choices
        ] + entries(tag, choices, recode, field)
    if kind == "Matrix":
        rows = [(row_name(question, cid), display(c)) for cid, c in choices]
        answers = ordered(question.get("Answers"), question.get("AnswerOrder"))
        if selector == "TE":
            return [
                field(f"{tag}_{row}_{aid}", f"{row_text}: {display(a)}", "text")
                for row, row_text in rows
                for aid, a in answers
            ]
        if question.get("SubSelector") == "MultipleAnswer":
            return [
                field(
                    f"{tag}_{row}_{code(recode, aid)}",
                    f"{row_text}: {display(a)}",
                    "choice",
                    choices=SELECTED,
                )
                for row, row_text in rows
                for aid, a in answers
            ]
        options = "; ".join(f"{code(recode, aid)}={display(a)}" for aid, a in answers)
        typed = [
            field(f"{tag}_{row_name(question, cid)}_TEXT", display(c), "text")
            for cid, c in choices
            if typed_in(c)
        ]
        return [
            field(f"{tag}_{row}", row_text, "choice", choices=options) for row, row_text in rows
        ] + typed
    if kind == "Slider":
        settings = question.get("Configuration") or {}
        bounds = {
            "min": str(settings.get("CSSliderMin", "")),
            "max": str(settings.get("CSSliderMax", "")),
        }
        return [
            field(f"{tag}_{cid}", f"{text}: {display(c)}", "number", **bounds) for cid, c in choices
        ]
    if kind == "TE" and selector == "FORM":
        return [field(f"{tag}_{cid}", f"{text}: {display(c)}", "text") for cid, c in choices]
    if kind == "TE":
        return [field(tag, text, "text")]
    return []


def entries(tag: str, choices: list[tuple[str, dict]], recode: dict, field) -> list:
    # Typed answers beside a choice, named by choice or by its code; older exports had one per question.
    typed = [(cid, c) for cid, c in choices if typed_in(c)]
    names = {
        f"{tag}_{key}_TEXT": f"{display(c)} (typed answer)"
        for cid, c in typed
        for key in (cid, code(recode, cid))
    }
    found = [field(name, text, "text") for name, text in names.items()]
    return found + ([field(f"{tag}_TEXT", "Typed answer", "text")] if typed else [])


def typed_in(choice: dict) -> bool:
    return str(choice.get("TextEntry")).lower() == "true"


def ordered(items: dict | list | None, order: list | None) -> list[tuple[str, dict]]:
    if not isinstance(items, dict):
        return []
    keys = [str(k) for k in order or []] or list(items)
    return [(k, items[k]) for k in keys if k in items]


def row_name(question: dict, cid: str) -> str:
    tags = question.get("ChoiceDataExportTags")
    return str(tags[cid]) if isinstance(tags, dict) and tags.get(cid) else cid


def code(recode: dict, cid: str) -> str:
    return str(recode.get(cid, cid))


def display(choice: dict) -> str:
    # labcatalog separates choices with semicolons.
    return plain(choice.get("Display") or "").replace(";", ",")


def item_id(column: str) -> str:
    # Keeps the minus of a code, so Q15_-1 and Q15_1 stay apart.
    return re.sub(r"[^a-z0-9_]", "_", column.lower().replace("-", "m"))


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
