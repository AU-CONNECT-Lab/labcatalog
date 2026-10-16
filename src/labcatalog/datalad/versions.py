import subprocess
from pathlib import Path

from pydantic import BaseModel

from labcatalog.datalad.annex import DATALAD_CONFIG, group_by_dataset
from labcatalog.paths import portable_path

ADJUSTED = "adjusted/"


class DataladRecord(BaseModel):
    path: str
    id: str
    commit: str
    tags: list[str] = []


def commit_of(root: Path, branch: str, paths: list[str]) -> str:
    head = run_git(root, "rev-parse", "--short", branch)
    changed = run_git(root, "status", "--porcelain", "--", *paths) or unsynced(root, branch)
    return f"{head}-modified" if changed else head


def unsynced(root: Path, branch: str) -> bool:
    # A synced adjusted branch is one git-annex commit on top of the original branch.
    return branch != "HEAD" and run_git(root, "rev-parse", "HEAD^") != run_git(
        root, "rev-parse", branch
    )


def tags_at(root: Path, branch: str) -> list[str]:
    # datalad save --version-tag tags the adjusted commit, a plain git tag the original one.
    found = {*run_git(root, "tag", "--points-at", "HEAD").split()}
    found.update(run_git(root, "tag", "--points-at", branch).split())
    return sorted(found)


def original_branch(root: Path) -> str:
    # git-annex on Windows works on adjusted/main(unlocked), a local branch that is never pushed.
    branch = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.startswith(ADJUSTED):
        return branch[len(ADJUSTED) : branch.index("(")]
    return "HEAD"


def datalad_records(project_root: Path, used: list[Path]) -> list[DataladRecord]:
    groups = group_by_dataset(used)
    records = (datalad_record(project_root, folder, paths) for folder, paths in groups.items())
    return [record for record in records if record]


def datalad_record(project_root: Path, folder: Path, paths: list[str]) -> DataladRecord | None:
    try:
        branch = original_branch(folder)
        return DataladRecord(
            path=portable_path(folder, project_root.resolve()).as_posix(),
            id=run_git(folder, "config", "--file", DATALAD_CONFIG.as_posix(), "datalad.dataset.id"),
            # Only the files labcatalog used decide whether the dataset counts as modified.
            commit=commit_of(folder, branch, paths),
            tags=tags_at(folder, branch),
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()
