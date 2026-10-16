from dataclasses import dataclass

from labcatalog.browse import as_set, score_values
from labcatalog.llm import CallMetadata, LLMClient, ToolSchema
from labcatalog.project import Project
from labcatalog.resolve import as_text_dict

SYSTEM = """You help a researcher find questions in their lab's catalog of questionnaires. You \
are given the researcher's request and the catalog: each instrument with its name, construct and \
labels, then its items as "item id | text".

Return the items that fit the request, judged by what each item asks rather than by shared \
words. Give a short reason for each. When a whole instrument fits, return it once with an empty \
item instead of listing every item. Use only instrument and item ids exactly as the catalog \
gives them. Return no matches when nothing fits; do not stretch."""

SCHEMA = ToolSchema(
    name="catalog_search",
    description="The items or instruments that fit the request.",
    input_schema={
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "instrument": {"type": "string", "description": "Instrument id."},
                        "item": {
                            "type": "string",
                            "description": "Item id, or empty for the whole instrument.",
                        },
                        "reason": {"type": "string", "description": "One short sentence."},
                    },
                    "required": ["instrument", "item", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matches"],
        "additionalProperties": False,
    },
)


@dataclass
class Match:
    instrument_id: str
    # None when the whole instrument fits.
    item_id: str | None
    reason: str


@dataclass
class Search:
    query: str
    matches: list[Match]
    # Matches naming an instrument or item the catalog does not have.
    dropped: int
    meta: CallMetadata

    @property
    def instruments(self) -> set[str]:
        return {m.instrument_id for m in self.matches}


def catalog_text(project: Project) -> str:
    lines = []
    for instrument in project.instruments.values():
        name = instrument.name + (
            f" ({instrument.abbreviation})" if instrument.abbreviation else ""
        )
        lines += ["", f"Instrument {instrument.id}: {name}"]
        if instrument.construct_name:
            lines.append(f"Construct: {instrument.construct_name}")
        if instrument.description:
            lines.append(f"Description: {instrument.description}")
        custom = {**score_values(instrument), **instrument.custom}
        labels = sorted({value for values in custom.values() for value in as_set(values)})
        if labels:
            lines.append(f"Labels: {', '.join(labels)}")
        for item in instrument.items:
            lines.append(f"{item.id} | {' / '.join(as_text_dict(item.text).values())}")
    return "\n".join(lines).strip()


def search_catalog(project: Project, query: str, client: LLMClient) -> Search:
    output, meta = client.complete_structured(
        system=SYSTEM,
        user_message=f"Request: {query}\n\nCatalog:\n{catalog_text(project)}",
        tool_schema=SCHEMA,
    )
    matches = []
    dropped = 0
    for found in output["matches"]:
        instrument = project.instruments.get(found["instrument"])
        item_id = found["item"] or None
        if instrument is None or (item_id and item_id not in {i.id for i in instrument.items}):
            dropped += 1
            continue
        matches.append(Match(instrument.id, item_id, " ".join(found["reason"].split())))
    return Search(query, matches, dropped, meta)
