import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from labcatalog.config import ProjectConfig
from labcatalog.data.manifest import used_paths
from labcatalog.datalad.annex import group_by_dataset
from labcatalog.datalad.bridge import run_datalad
from labcatalog.datalad.freeze import push_targets, push_to
from labcatalog.datalad.versions import ADJUSTED, run_git


@dataclass
class DatasetState:
    root: Path
    # Paths with changes not yet saved, as git status gives them.
    changed: list[str]
    sibling: str | None
    # Saved versions the sibling does not have; None when nothing was ever pushed there.
    ahead: int | None
    # Versions on the sibling not merged here, as of the last update.
    behind: int | None
    # Bytes of the dataset's annexed files here, and in all; None without git-annex.
    present: int | None = None
    total: int | None = None


def project_datasets(config: ProjectConfig, root: Path) -> list[Path]:
    # The datasets holding what the project reads, and the one holding the project folder.
    return sorted(group_by_dataset([*used_paths(config, root), root]))


def deepest_first(roots: list[Path]) -> list[Path]:
    return sorted(roots, key=lambda r: len(r.parts), reverse=True)


def branch_name(root: Path) -> str:
    # On Windows git-annex works on adjusted/main(unlocked); main is what siblings get.
    branch = run_git(root, "branch", "--show-current")
    if branch.startswith(ADJUSTED):
        return branch[len(ADJUSTED) : branch.index("(")]
    return branch


def changed_paths(root: Path) -> list[str]:
    lines = run_git(root, "status", "--porcelain").splitlines()
    return [line[3:].strip('"') for line in lines if line.strip()]


def dataset_state(root: Path) -> DatasetState:
    sibling = push_targets([root])[root]
    ahead = behind = None
    branch = branch_name(root)
    if sibling and branch:
        remote = f"refs/remotes/{sibling}/{branch}"
        if has_ref(root, remote):
            counts = run_git(root, "rev-list", "--left-right", "--count", f"{branch}...{remote}")
            ahead, behind = (int(n) for n in counts.split())
    present, total = space(root) or (None, None)
    return DatasetState(root, changed_paths(root), sibling, ahead, behind, present, total)


def space(root: Path) -> tuple[int, int] | None:
    try:
        found = json.loads(run_git(root, "annex", "info", "--fast", "--bytes", "--json", "."))
    except subprocess.CalledProcessError:
        return None
    return int(found["local annex size"]), int(found["size of annexed files in working tree"])


def get_all(root: Path, datalad: str) -> None:
    run_datalad(datalad, ["get", "."], cwd=root)


def drop_all(root: Path, datalad: str) -> None:
    # DataLad refuses to drop a file it cannot find a copy of elsewhere.
    run_datalad(datalad, ["drop", "."], cwd=root)


def clone(url: str, folder: Path, datalad: str) -> Path:
    name = re.split(r"[/\\:]", url.rstrip("/\\"))[-1].removesuffix(".git")
    target = folder / name
    run_datalad(datalad, ["clone", url, str(target)])
    return target


def has_ref(root: Path, ref: str) -> bool:
    try:
        run_git(root, "rev-parse", "--verify", "--quiet", ref)
    except subprocess.CalledProcessError:
        return False
    return True


def dataset_states(roots: list[Path]) -> list[DatasetState]:
    return [dataset_state(root) for root in roots]


def save_datasets(
    roots: list[Path], message: str, datalad: str, author: str | None = None
) -> list[Path]:
    # Deepest first, so a dataset above records the new versions of those inside it.
    saved = []
    # Serving several people, the version carries the name given at the window.
    env = {"GIT_AUTHOR_NAME": author} if author else None
    for root in deepest_first(roots):
        if changed_paths(root):
            run_datalad(datalad, ["save", "-m", message], cwd=root, env=env)
            saved.append(root)
    return saved


def update_datasets(roots: list[Path], datalad: str) -> list[Path]:
    # Shallowest first, so a dataset inside merges after the one above has moved it.
    updated = []
    for root, sibling in push_targets(sorted(roots, key=lambda r: len(r.parts))).items():
        if sibling is not None:
            run_datalad(datalad, ["update", "--how", "merge", "-s", sibling], cwd=root)
            updated.append(root)
    return updated


def push_datasets(roots: list[Path], datalad: str) -> list[Path]:
    # Deepest first, so a sibling never gets a dataset that points at versions it lacks.
    pushed = []
    for root, sibling in push_targets(deepest_first(roots)).items():
        if sibling is not None:
            push_to(root, sibling, datalad)
            pushed.append(root)
    return pushed


def state_text(state: DatasetState) -> str:
    parts = [f"{len(state.changed)} unsaved change(s)"] if state.changed else []
    if state.sibling is None:
        parts.append("no single sibling to push to")
    elif state.ahead is None:
        parts.append(f"never pushed to {state.sibling}")
    else:
        if state.ahead:
            parts.append(f"{state.ahead} saved version(s) not pushed to {state.sibling}")
        if state.behind:
            parts.append(f"{state.behind} new version(s) on {state.sibling}")
    text = "; ".join(parts) or f"saved, and the same as {state.sibling}"
    if state.total:
        text += f"; {size_text(state.present)} of {size_text(state.total)} here"
    return text


def size_text(count: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if count < 1000 or unit == "GB":
            break
        count /= 1000
    return f"{count:.0f} {unit}" if unit == "bytes" else f"{count:.1f} {unit}"


def summary(states: list[DatasetState]) -> tuple[str, str]:
    # A few words for the header, and how much they ask for attention: warn, info or ok.
    if unsaved := sum(len(s.changed) for s in states):
        return f"{unsaved} unsaved", "warn"
    if ahead := sum(s.ahead or 0 for s in states):
        return f"{ahead} to push", "warn"
    if behind := sum(s.behind or 0 for s in states):
        return f"{behind} to update", "info"
    if any(s.sibling and s.ahead is None for s in states):
        return "Not pushed yet", "warn"
    return "Data saved", "ok"
