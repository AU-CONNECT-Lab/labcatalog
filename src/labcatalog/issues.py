from typing import Literal

from pydantic import BaseModel

IssueLevel = Literal["error", "warning", "info"]


class Issue(BaseModel):
    level: IssueLevel
    code: str
    message: str
    location: str | None = None


def has_errors(issues: list[Issue]) -> bool:
    raise NotImplementedError
