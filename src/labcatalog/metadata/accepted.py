import getpass
import io
import subprocess
from datetime import date
from pathlib import Path

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.issues import Issue
from labcatalog.metadata import records
from labcatalog.project import load_model
from labcatalog.schema import StrictModel


class AcceptedWarning(StrictModel):
    code: str
    location: str | None = None
    message: str
    reason: str
    by: str
    date: date


class AcceptedFile(StrictModel):
    accepted: list[AcceptedWarning] = []


def load(root: Path, issues: list[Issue]) -> list[AcceptedWarning]:
    path = root / defaults.ACCEPTED_FILENAME
    if not path.is_file():
        return []
    found = load_model(path, AcceptedFile, root, issues)
    return found.accepted if found else []


def matches(issue: Issue, entry: AcceptedWarning) -> bool:
    # The whole message must match, so a warning that names new people shows again.
    return (issue.code, issue.location, issue.message) == (
        entry.code,
        entry.location,
        entry.message,
    )


def split(issues: list[Issue], entries: list[AcceptedWarning]) -> tuple[list[Issue], list[Issue]]:
    # Errors are never hidden, whatever the file says.
    hidden = [i for i in issues if i.level == "warning" and any(matches(i, e) for e in entries)]
    return [i for i in issues if i not in hidden], hidden


def accept(root: Path, issue: Issue, reason: str) -> None:
    data = read(root)
    entry = CommentedMap()
    entry.fa.set_flow_style()
    entry["code"] = issue.code
    if issue.location:
        entry["location"] = issue.location
    entry["message"] = records.as_text(issue.message)
    entry["reason"] = records.as_text(reason.strip())
    entry["by"] = records.as_text(who(root))
    entry["date"] = date.today()
    data["accepted"].append(entry)
    write(root, data)


def withdraw(root: Path, issue: Issue) -> None:
    data = read(root)
    kept = [e for e in data["accepted"] if not matches(issue, AcceptedWarning(**e))]
    data["accepted"] = CommentedSeq(kept)
    write(root, data)


def read(root: Path) -> CommentedMap:
    path = root / defaults.ACCEPTED_FILENAME
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    data = records.load(text)
    if not data.get("accepted"):
        data["accepted"] = CommentedSeq()
    return data


def write(root: Path, data: CommentedMap) -> None:
    out = io.StringIO()
    records.round_trip().dump(data, out)
    (root / defaults.ACCEPTED_FILENAME).write_text(out.getvalue(), encoding="utf-8", newline="\n")


def nobody() -> str | None:
    return None


# The name given at the window, when one labcatalog serves several people; serving points it there.
named = nobody


def who(root: Path) -> str:
    # The name given at the window, else the one git records, else the computer's user name.
    if given := named():
        return given
    try:
        found = subprocess.run(
            ["git", "config", "user.name"], cwd=root, capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        found = ""
    return found or getpass.getuser()
