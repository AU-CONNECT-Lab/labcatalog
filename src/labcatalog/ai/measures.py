from dataclasses import dataclass

from labcatalog.ai.scoring import answer, pdf_text, reference_pdfs
from labcatalog.data.resolve import as_text_dict
from labcatalog.llm import CallMetadata, LLMClient, ToolSchema
from labcatalog.metadata.bibliography import citation
from labcatalog.project import Project

SYSTEM = """You help a researcher write the Measures section of a paper. You are given a \
questionnaire's reference (its paper or manual, converted from PDF) and the instrument's name, \
construct and items as the researcher's catalog lists them.

Write one or two sentences, in English and in the present tense, that say what the instrument \
measures and what respondents are asked to do. Say only what the reference supports. Do not \
give any numbers, the number of items, the response scale, how it is scored, reliability, \
validity statistics or citations: the rest of the paragraph adds those from the catalog. Start \
with "It", as the sentences follow one that names the instrument.

In the notes, list anything in the reference that disagrees with the catalog, such as a \
different number of items or a different construct, and anything you were unsure of. Leave the \
notes empty when there is nothing to report."""

SCHEMA = ToolSchema(
    name="measures_description",
    description="A sentence or two on what the instrument measures, and what to check.",
    input_schema={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "One or two sentences."},
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Disagreements with the catalog, and doubts.",
            },
        },
        "required": ["description", "notes"],
        "additionalProperties": False,
    },
)


@dataclass
class Draft:
    description: str
    notes: list[str]
    meta: CallMetadata


def description_request(project: Project, instrument_id: str) -> str:
    instrument = project.instruments[instrument_id]
    name = instrument.name + (f" ({instrument.abbreviation})" if instrument.abbreviation else "")
    lines = [f"Instrument: {name}"]
    if instrument.construct_name:
        lines.append(f"Construct: {instrument.construct_name}")
    lines += ["", "Items (id | text | answer):"]
    for item in instrument.items:
        text = " / ".join(as_text_dict(item.text).values())
        lines.append(f"{item.id} | {text} | {answer(instrument, item)}")
    for reference, path in reference_pdfs(project, instrument):
        cited = citation(project.bibliography, reference.key)
        lines += ["", f"Reference: {cited}", "<reference>", pdf_text(path), "</reference>"]
    return "\n".join(lines)


def draft_description(project: Project, instrument_id: str, client: LLMClient) -> Draft:
    output, meta = client.complete_structured(
        system=SYSTEM,
        user_message=description_request(project, instrument_id),
        tool_schema=SCHEMA,
    )
    return Draft(" ".join(output["description"].split()), output["notes"], meta)
