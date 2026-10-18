from dataclasses import dataclass
from pathlib import Path

from labcatalog.datalad.bridge import run_datalad
from labcatalog.datalad.versions import run_git

# How datalad run starts the message of the version it saves.
RUN_RECORD = "[DATALAD RUNCMD]"
SHOWN = 50
RECORD = "\x1e"
FIELD = "\x1f"


@dataclass
class Saved:
    commit: str
    author: str
    # ISO 8601, with the saver's time zone.
    when: str
    message: str
    files: list[str]

    @property
    def ran(self) -> bool:
        return self.message.startswith(RUN_RECORD)

    @property
    def title(self) -> str:
        return self.message.removeprefix(RUN_RECORD).strip()


def history(root: Path, branch: str, count: int = SHOWN) -> list[Saved]:
    # The branch siblings get, since on Windows the checked-out one adds git-annex's own versions.
    text = run_git(
        root,
        "log",
        branch,
        f"-n{count}",
        f"--format={RECORD}%H{FIELD}%an{FIELD}%aI{FIELD}%s",
        "--name-only",
    )
    found = []
    # The output comes stripped, and Python counts the separator itself as white space.
    for record in filter(None, text.split(RECORD)):
        head, *files = record.strip("\n").split("\n")
        commit, author, when, message = head.split(FIELD)
        found.append(Saved(commit, author, when, message, [f for f in files if f]))
    return found


def rerun(root: Path, commit: str, datalad: str) -> None:
    # As the prepare steps run: only the recorded outputs are saved, so other changes may wait.
    run_datalad(datalad, ["rerun", "--explicit", commit], cwd=root)
