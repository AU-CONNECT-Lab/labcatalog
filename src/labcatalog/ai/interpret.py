from dataclasses import dataclass

from labcatalog.llm import CallMetadata, LLMClient, ToolSchema
from labcatalog.reports import tables
from labcatalog.reports.tables import PaperTable

SYSTEM = """You help a researcher read the result of one analysis. You are given its tables, \
as they would appear in a paper, and the results paragraph written from them.

Write a short interpretation, three to five sentences in English and in the past tense, of what \
the result shows: the direction and size of the effects and which ones matter. Use only numbers \
that are in the tables. Name a benchmark only together with its source, such as Cohen's \
conventions for effect sizes. Do not claim that one variable causes another unless the design \
supports it, and do not invent anything about the design that the tables do not say.

In the notes, list what the researcher should check or keep in mind before using the \
interpretation: small or uneven samples, many tests, wide confidence intervals, fit indices or \
warnings in the table notes, and anything you were unsure of. Leave the notes empty when there \
is nothing to report."""

SCHEMA = ToolSchema(
    name="result_interpretation",
    description="A short interpretation of one analysis, and what to check.",
    input_schema={
        "type": "object",
        "properties": {
            "interpretation": {"type": "string", "description": "Three to five sentences."},
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What to check before using it.",
            },
        },
        "required": ["interpretation", "notes"],
        "additionalProperties": False,
    },
)


@dataclass
class Interpretation:
    text: str
    notes: list[str]
    meta: CallMetadata


def interpretation_request(shown: list[PaperTable], paragraph: str) -> str:
    parts = [tables.plain(table) for table in shown]
    return "\n\n".join([*parts, f"Results paragraph: {paragraph}"])


def interpret(shown: list[PaperTable], paragraph: str, client: LLMClient) -> Interpretation:
    output, meta = client.complete_structured(
        system=SYSTEM,
        user_message=interpretation_request(shown, paragraph),
        tool_schema=SCHEMA,
    )
    return Interpretation(" ".join(output["interpretation"].split()), output["notes"], meta)
