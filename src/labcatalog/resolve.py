from pydantic import BaseModel

from labcatalog.project import Project
from labcatalog.schema import ResponseOption


class ResolvedVariable(BaseModel):
    column: str
    instrument_id: str
    item_id: str
    dataset: str
    study: str
    wave: str
    reporter: str
    modality: str
    target: str | None = None
    text: dict[str, str]
    response_options: list[ResponseOption]
    reverse: bool
    reversed_in_data: bool
    subscales: list[str] = []


class ResolvedScore(BaseModel):
    key: str
    instrument_id: str
    score_id: str
    dataset: str
    label: str
    method: str
    columns: list[str]
    reverse_columns: list[str]
    reverse_bounds: dict[str, tuple[float, float]]
    reversed_in_data: bool
    min_valid: int | None = None
    existing_column: str | None = None


class Catalog(BaseModel):
    variables: list[ResolvedVariable]
    scores: list[ResolvedScore]

    def variables_for(self, dataset: str) -> list[ResolvedVariable]:
        raise NotImplementedError

    def scores_for(self, dataset: str) -> list[ResolvedScore]:
        raise NotImplementedError


def render_variable_name(template: str, **fields: str) -> str:
    raise NotImplementedError


def resolve_catalog(project: Project) -> Catalog:
    raise NotImplementedError
