import os
import re
from pathlib import Path

POINTER = b"/annex/objects/"
SIZE = re.compile(r"^[A-Z0-9]+-s(\d+)-")
DATALAD_CONFIG = Path(".datalad") / "config"


def is_placeholder(path: Path) -> bool:
    # Until its content is fetched, git-annex leaves a pointer file (Windows) or a broken link (Linux).
    if path.is_symlink() and not path.exists():
        return "annex/objects" in os.readlink(path).replace("\\", "/")
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.read(len(POINTER)) == POINTER


def annexed_size(path: Path) -> int | None:
    # A git-annex key names the content's size, as in SHA256E-s1234--<hash>.tsv; some keys do not.
    if path.is_symlink():
        target = os.readlink(path)
    else:
        with path.open("rb") as handle:
            target = handle.read(1024).decode("utf-8", errors="replace")
    found = SIZE.search(target.replace("\\", "/").rsplit("/", 1)[-1])
    return int(found[1]) if found else None


def fetch_advice(path: Path) -> str:
    return f'the content of {path} is not on this computer; get it with: datalad get "{path}"'


def resolved(path: Path) -> Path:
    # Resolving a file itself would follow a locked annex link into .git/annex/objects.
    return path.resolve() if path.is_dir() else path.parent.resolve() / path.name


def dataset_root(path: Path) -> Path | None:
    # The nearest one, so a file in a subdataset belongs to the subdataset.
    folder = resolved(path) if path.is_dir() else resolved(path).parent
    return next((f for f in (folder, *folder.parents) if (f / DATALAD_CONFIG).is_file()), None)


def group_by_dataset(paths: list[Path]) -> dict[Path, list[str]]:
    found: dict[Path, list[str]] = {}
    for path in paths:
        if folder := dataset_root(path):
            found.setdefault(folder, []).append(resolved(path).relative_to(folder).as_posix())
    return found
