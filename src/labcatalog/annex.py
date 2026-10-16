import os
from pathlib import Path

POINTER = b"/annex/objects/"
DATALAD_CONFIG = Path(".datalad") / "config"


def is_placeholder(path: Path) -> bool:
    # Until its content is fetched, git-annex leaves a pointer file (Windows) or a broken link (Linux).
    if path.is_symlink() and not path.exists():
        return "annex/objects" in os.readlink(path).replace("\\", "/")
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.read(len(POINTER)) == POINTER


def fetch_advice(path: Path) -> str:
    return f'the content of {path} is not on this computer; get it with: datalad get "{path}"'


def dataset_root(path: Path) -> Path | None:
    # The nearest one, so a file in a subdataset belongs to the subdataset.
    folder = path.parent.resolve()
    return next((f for f in (folder, *folder.parents) if (f / DATALAD_CONFIG).is_file()), None)
