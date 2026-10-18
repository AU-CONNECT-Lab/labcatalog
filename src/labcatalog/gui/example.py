import hashlib
import shutil
from functools import cache
from pathlib import Path

from labcatalog import defaults
from labcatalog.gui import preferences
from labcatalog.project import EXAMPLE_DIR, init_project

# Which version of the installed example a copy was made from.
MARK = ".labcatalog_example"


def example_folder() -> Path:
    return preferences.folder() / "example"


def example_copy() -> Path:
    # The window's own copy, so trying the Set up page never changes the installed package.
    folder = example_folder()
    if not folder.exists():
        init_project(folder)
        (folder / MARK).write_text(fingerprint(), encoding="utf-8")
    return folder


@cache
def fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted(EXAMPLE_DIR.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(path.relative_to(EXAMPLE_DIR).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def outdated(root: Path | None) -> bool:
    # The window's copy of the example, made from an example that has changed since.
    if root is None or root.resolve() != example_folder().resolve():
        return False
    mark = root / MARK
    return not mark.is_file() or mark.read_text(encoding="utf-8") != fingerprint()


def reset_example() -> Path:
    if example_folder().exists():
        shutil.rmtree(example_folder())
    return example_copy()


def start_folder() -> Path:
    # The project open when the window last closed, or the example the first time.
    last = preferences.mine().get(preferences.LAST_PROJECT)
    if last and (Path(last) / defaults.CONFIG_FILENAME).is_file():
        return Path(last)
    return example_copy()
