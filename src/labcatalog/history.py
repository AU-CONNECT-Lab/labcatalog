import subprocess
from dataclasses import dataclass
from pathlib import Path

RECORD = "\x1e"
FIELD = "\x1f"
LOG_FORMAT = f"{RECORD}%h{FIELD}%ad{FIELD}%an{FIELD}%s"
UNCOMMITTED = "Uncommitted changes"


@dataclass
class Change:
    date: str
    author: str
    message: str
    diff: str
    commit: str | None = None


def file_history(root: Path, path: str) -> list[Change] | None:
    # None when there is no history to show: git is not installed or the project is not in git.
    try:
        inside = git(root, "rev-parse", "--is-inside-work-tree")
    except FileNotFoundError:
        return None
    if inside.strip() != "true":
        return None
    changes = []
    status = git(root, "status", "--porcelain", "--", path)
    if status.startswith("??"):
        changes.append(Change("", "", UNCOMMITTED, "This file is not in git yet."))
    elif status:
        changes.append(Change("", "", UNCOMMITTED, git(root, "diff", "HEAD", "--", path).strip()))
    log = git(
        root, "log", "--follow", "--patch", "--date=short", f"--format={LOG_FORMAT}", "--", path
    )
    for record in log.split(RECORD)[1:]:
        header, _, diff = record.partition("\n")
        commit, date, author, message = header.split(FIELD)
        changes.append(Change(date, author, message, diff.strip("\n"), commit))
    return changes


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return done.stdout if done.returncode == 0 else ""
