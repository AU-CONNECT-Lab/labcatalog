from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

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


class Item(StrictModel):
    id: str
    text: Text
    response_set: str | None = None
    reverse: bool = False
    subscales: list[str] = []


class Score(StrictModel):
    id: str
    label: str
    method: Literal["sum", "mean"]
    items: list[str]
    missing_rule: Literal["complete", "prorate", "zero"] = "complete"
    min_valid: int | None = None


class Reference(StrictModel):
    citation: str
    doi: str | None = None
    pdf: str | None = None
    url: str | None = None


class Instrument(StrictModel):
    id: str
    name: str
    abbreviation: str | None = None
    kind: str = "questionnaire"
    construct_name: str | None = None
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
    administrations: list[Administration] = []


def json_schemas() -> dict[str, dict[str, Any]]:
    raise NotImplementedError
