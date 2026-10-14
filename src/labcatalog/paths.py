from pathlib import Path


def expand_path(value: str, base: Path) -> Path:
    raise NotImplementedError


def clean_file_url(value: str) -> str:
    raise NotImplementedError


def portable_path(path: Path, project_root: Path) -> Path:
    raise NotImplementedError


def posix_str(path: Path | str) -> str:
    raise NotImplementedError


def stored_path(value: str) -> Path:
    raise NotImplementedError


def resolve_existing(value: str | None, base: Path) -> Path | None:
    raise NotImplementedError
