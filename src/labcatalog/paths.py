import os
import re
from pathlib import Path
from urllib.parse import unquote


def expand_path(value: str, base: Path) -> Path:
    # ~ and environment variables let one shared config point at each person's own sync folder.
    expanded = os.path.expandvars(os.path.expanduser(clean_file_url(value)))
    path = stored_path(expanded)
    return path if path.is_absolute() else base / path


def clean_file_url(value: str) -> str:
    if value.lower().startswith("file://"):
        value = value[len("file://") :]
        # file:///C:/... names a Windows drive, not a folder "C:" under the root.
        if re.match(r"/[A-Za-z]:[/\\]", value):
            value = value[1:]
    if "%" in value:
        value = unquote(value)
    return value


def portable_path(path: Path, project_root: Path) -> Path:
    try:
        return Path(os.path.relpath(path, project_root))
    except ValueError:
        # Different Windows drives have no relative path between them.
        return Path(path)


def posix_str(path: Path | str) -> str:
    return Path(path).as_posix()


def stored_path(value: str) -> Path:
    return Path(value.replace("\\", "/"))
