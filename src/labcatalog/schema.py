from typing import Any, Literal

from pydantic import BaseModel, ConfigDict
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import core_schema

# Unknown keys are errors so typos in YAML surface at validate time.
STRICT = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

Text = str | dict[str, str]


class StrictModel(BaseModel):
    model_config = STRICT


class ResponseOption(StrictModel):
    value: int | float | str
    label: str


class ResponseSet(StrictModel):
    id: str
    options: list[ResponseOption]


ItemType = Literal["choice", "number", "text"]
# A score its own script computes, read from the dataset's scores file.
SCRIPT = "script"


class Item(StrictModel):
    id: str
    # A short name for tables and text, such as "Child age"; the item's text when left out.
    label: str | None = None
    text: Text
    type: ItemType = "choice"
    response_set: str | None = None
    min: float | None = None
    max: float | None = None
    reverse: bool = False
    subscales: list[str] = []
    custom: dict[str, Any] = {}


class Score(StrictModel):
    id: str
    label: str
    method: Literal["sum", "mean", "script"]
    items: list[str] = []
    missing_rule: Literal["complete", "prorate", "zero"] = "complete"
    min_valid: int | None = None
    custom: dict[str, Any] = {}


class Reference(StrictModel):
    key: str
    pdf: str | None = None


class Instrument(StrictModel):
    id: str
    name: str
    abbreviation: str | None = None
    modality: str = "questionnaire"
    # A form about the people, not a scale: not scored, charted or checked for references.
    demographics: bool = False
    construct_name: str | None = None
    # A sentence or two for the Measures paragraph, written or checked by a person.
    description: str | None = None
    # This instrument's own wording of the Measures template's parts, over the project's.
    measures: str | dict[str, str] | None = None
    instructions: Text | None = None
    response_sets: list[ResponseSet] = []
    default_response_set: str | None = None
    items: list[Item] = []
    scores: list[Score] = []
    references: list[Reference] = []
    license: str | None = None
    items_public: bool = False
    sensitive: bool = False
    custom: dict[str, Any] = {}


class ItemOverride(StrictModel):
    item: str
    dataset: str | None = None
    text: Text | None = None
    response_set: str | None = None
    dropped: bool = False


class Administration(StrictModel):
    instrument: str
    datasets: list[str]
    target: str | None = None
    abbreviation: str | None = None
    reversed_in_data: bool = False
    overrides: list[ItemOverride] = []
    custom: dict[str, Any] = {}


class StudyContent(StrictModel):
    study: str
    # Modality to how its data were collected and processed in this study.
    methods: dict[str, str] = {}
    # This study's own wording of the Participants template's parts, over the project's.
    participants: str | dict[str, str] | None = None
    administrations: list[Administration] = []


class LenientStrings(GenerateJsonSchema):
    # Text fields take YAML numbers too (wave: 1), so editors must not flag them.
    def str_schema(self, schema: core_schema.StringSchema) -> JsonSchemaValue:
        return {**super().str_schema(schema), "type": ["string", "number"]}
