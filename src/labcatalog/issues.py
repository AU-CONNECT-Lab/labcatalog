from typing import Any, Literal

from pydantic import BaseModel, ValidationError

IssueLevel = Literal["error", "warning", "info"]

PLAIN_MESSAGES = {
    "extra_forbidden": "unknown key; check the spelling",
    "missing": "required but missing",
}


class Issue(BaseModel):
    level: IssueLevel
    code: str
    message: str
    location: str | None = None
    # What the problem is about, such as the dataset and column, for the Fix panel.
    details: dict[str, Any] = {}


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def summarize_issues(issues: list[Issue]) -> str:
    if not issues:
        return "No problems found."
    n_errors = sum(issue.level == "error" for issue in issues)
    n_warnings = sum(issue.level == "warning" for issue in issues)
    return f"{n_errors} error(s), {n_warnings} warning(s)"


def issues_from_validation_error(error: ValidationError, location: str, data: Any) -> list[Issue]:
    issues = []
    for detail in error.errors():
        path = field_path(detail["loc"], data)
        text = PLAIN_MESSAGES.get(detail["type"], detail["msg"])
        message = f"{path}: {text}" if path else text
        issues.append(Issue(level="error", code=detail["type"], message=message, location=location))
    return issues


def field_path(loc: tuple[int | str, ...], data: Any) -> str:
    # The data tells list positions from integer keys such as wave 1; positions are 1-based.
    path = ""
    node = data
    for part in loc:
        if isinstance(node, list) and isinstance(part, int):
            path += f"[{part + 1}]"
        else:
            path += f".{part}" if path else str(part)
        node = node[part] if isinstance(node, (dict, list)) and part in index(node) else None
    return path


def index(node: dict | list) -> Any:
    return node if isinstance(node, dict) else range(len(node))
