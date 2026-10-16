from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from labcatalog import defaults
from labcatalog.ai.scoring import pdf_text
from labcatalog.codebook.core import ITEM_TYPES, METHODS, MISSING_RULES, number_or_text, yaml_text
from labcatalog.exceptions import LLMError
from labcatalog.llm import CallMetadata, LLMClient, ToolSchema
from labcatalog.metadata.editing import free_instrument_path

SYSTEM = """You enter questionnaires into a research lab's catalog. You are given an \
instrument's paper or manual, converted from PDF, and the ID the lab chose for the instrument. \
Draft the instrument's entry from the document: its name, abbreviation, the construct it \
measures, the instructions to respondents, the response options, every item and every score.

Take everything from the document, and copy the item wording and the instructions word for \
word. Where the document does not say, leave the field empty; do not fill it in from what you \
know about the instrument. If the document describes several instruments or versions, draft \
the one it presents as the main one and name the others in the notes.

IDs use lower-case letters, digits and underscores. Item IDs are the abbreviation and the \
item's number (ems_1); score IDs are the abbreviation and the score's name (ems_total). An \
item answered by choosing an option has type choice; one answered with an amount, such as age \
or hours, has type number, with min and max when the document gives them; an open answer has \
type text.

Give each distinct set of response options one response set, with the values the scoring \
uses. If the document prints labels but no values, number the options from the value its \
scoring implies, or from 1 if it implies none, and say so in the notes. Set \
default_response_set to the set most items use, and leave an item's response_set empty when \
it uses that set or is not a choice item. Mark an item reverse only when the document says it \
is reverse-scored.

Add a score for every total and subscale the document defines, with its items and its method \
(sum or mean). Set missing_rule to complete unless the document lets a score be computed with \
answers missing: prorate when the missing answers take the mean of the answered ones, with \
min_valid the fewest answered items it allows (7 for nine items with at most two missing); \
zero when missing answers count as 0.

In the notes, list each decision the document did not settle, anything you were unsure of, \
and anything in the document that seems inconsistent, such as a scoring key that names items \
the instrument does not have. Leave the notes empty when there is nothing to report."""

STRING = {"type": "string"}
OPTIONAL = {"type": "string", "description": "Empty when the document does not say."}


def strict(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def choice(values: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


SCHEMA = ToolSchema(
    name="instrument_draft",
    description="The instrument's entry as the document gives it, and what to check.",
    input_schema=strict(
        {
            "name": STRING,
            "abbreviation": OPTIONAL,
            "construct_name": OPTIONAL,
            "instructions": OPTIONAL,
            "response_sets": array(
                strict({"id": STRING, "options": array(strict({"value": STRING, "label": STRING}))})
            ),
            "default_response_set": OPTIONAL,
            "items": array(
                strict(
                    {
                        "id": STRING,
                        "text": STRING,
                        "type": choice(ITEM_TYPES),
                        "response_set": OPTIONAL,
                        "min": OPTIONAL,
                        "max": OPTIONAL,
                        "reverse": {"type": "boolean"},
                    }
                )
            ),
            "scores": array(
                strict(
                    {
                        "id": STRING,
                        "label": STRING,
                        "method": choice(METHODS),
                        "items": array(STRING),
                        "missing_rule": choice(MISSING_RULES),
                        "min_valid": OPTIONAL,
                    }
                )
            ),
            "notes": array(STRING),
        }
    ),
)


@dataclass
class InstrumentDraft:
    path: Path
    notes: list[str]
    meta: CallMetadata


def draft_path(root: Path, instrument_id: str) -> Path:
    return root / defaults.DRAFTS_DIR / f"{instrument_id}.yaml"


def instrument_request(instrument_id: str, pdf: Path) -> str:
    text = pdf_text(pdf)
    if not text.strip():
        raise LLMError(f"{pdf.name} has no text to read; a scanned PDF needs OCR first")
    return "\n".join([f"Instrument ID: {instrument_id}", "", "<document>", text, "</document>"])


def draft_instrument(
    root: Path, instrument_id: str, pdf: Path, client: LLMClient
) -> InstrumentDraft:
    free_instrument_path(root, instrument_id)
    output, meta = client.complete_structured(
        system=SYSTEM, user_message=instrument_request(instrument_id, pdf), tool_schema=SCHEMA
    )
    notes = [" ".join(line.split()) for line in output["notes"]]
    modeline, body = yaml_text(instrument_document(instrument_id, output), "instrument").split(
        "\n", 1
    )
    lines = [
        modeline,
        f"# Drafted by {meta.provider} {meta.model} on {date.today().isoformat()} from {pdf.name}.",
        "# Check it against the PDF, add the reference at the end, then move it to instruments/.",
        *(["# Notes from the model:"] if notes else []),
        *[f"# - {line}" for line in notes],
        body.rstrip("\n"),
        "# references:",
        f"#   - {{key: <its key in references.bib>, pdf: {pdf.name}}}",
    ]
    path = draft_path(root, instrument_id)
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return InstrumentDraft(path, notes, meta)


def instrument_document(instrument_id: str, output: dict[str, Any]) -> dict[str, Any]:
    default = output["default_response_set"].strip()
    document: dict[str, Any] = {"id": instrument_id, "name": output["name"].strip()}
    document |= given(
        {key: output[key] for key in ("abbreviation", "construct_name", "instructions")}
    )
    if output["response_sets"]:
        document["response_sets"] = [
            {
                "id": response_set["id"],
                "options": [
                    {"value": number_or_text(o["value"].strip()), "label": o["label"]}
                    for o in response_set["options"]
                ],
            }
            for response_set in output["response_sets"]
        ]
    document |= given({"default_response_set": default})
    if output["items"]:
        document["items"] = [item_fields(item, default) for item in output["items"]]
    if output["scores"]:
        document["scores"] = [score_fields(score) for score in output["scores"]]
    return document


def item_fields(item: dict[str, Any], default: str) -> dict[str, Any]:
    fields = {"id": item["id"], "text": item["text"]}
    if item["type"] != "choice":
        fields["type"] = item["type"]
    elif item["response_set"].strip() != default:
        fields["response_set"] = item["response_set"].strip()
    fields |= given({"min": item["min"], "max": item["max"]}, number=True)
    if item["reverse"]:
        fields["reverse"] = True
    return fields


def score_fields(score: dict[str, Any]) -> dict[str, Any]:
    fields = {key: score[key] for key in ("id", "label", "method", "items")}
    if score["missing_rule"] != "complete":
        fields["missing_rule"] = score["missing_rule"]
    return fields | given({"min_valid": score["min_valid"]}, number=True)


def given(fields: dict[str, str], number: bool = False) -> dict[str, Any]:
    # The model leaves a field empty when the document does not say.
    kept = {key: value.strip() for key, value in fields.items() if value.strip()}
    return {key: number_or_text(value) for key, value in kept.items()} if number else kept
