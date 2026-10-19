import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from labcatalog.config import DatasetConfig
from labcatalog.datalad.annex import annexed_size, is_placeholder
from labcatalog.exceptions import DataSourceError
from labcatalog.paths import expand_path

ID = "{id}"
FILES = "files"
WILDCARDS = {
    ID: "(?P<id>[^/]+)",
    "**/": "(?:.*/)?",
    "**": ".*",
    "*": "[^/]*",
    "?": "[^/]",
}


class FolderSource:
    # Only paths are read, so files whose content is not downloaded still count.
    def read(self, dataset: DatasetConfig, project_root: Path, id_column: str) -> pd.DataFrame:
        folder = expand_path(dataset.path, project_root)
        if not folder.is_dir():
            raise DataSourceError(f"{dataset.name}: folder not found: {folder}")
        counts = Counter(person for person, _ in matched(dataset, project_root))
        ids = sorted(counts)
        return pd.DataFrame({id_column: ids, FILES: [str(counts[i]) for i in ids]})


@dataclass
class FolderSize:
    files: int = 0
    # Bytes of every file, and of those whose content is on this computer.
    size: int = 0
    here: int = 0
    here_size: int = 0
    # Files not here whose size their annex key does not give.
    unknown: int = 0


@dataclass
class FolderFile:
    id: str
    path: Path
    # None when its content is not here and its annex key does not give its size.
    size: int | None
    here: bool


def folder_size(dataset: DatasetConfig, project_root: Path) -> FolderSize:
    found = FolderSize()
    for file in folder_files(dataset, project_root):
        found.files += 1
        found.size += file.size or 0
        found.unknown += file.size is None
        if file.here:
            found.here += 1
            found.here_size += file.size
    return found


def folder_files(dataset: DatasetConfig, project_root: Path) -> list[FolderFile]:
    files = []
    for person, path in matched(dataset, project_root):
        here = not is_placeholder(path)
        size = path.stat().st_size if here else annexed_size(path)
        files.append(FolderFile(person, path, size, here))
    return files


def matched(dataset: DatasetConfig, project_root: Path) -> Iterator[tuple[str, Path]]:
    # The files the dataset's rule matches, as the catalog counts them, each with its ID.
    folder = expand_path(dataset.path, project_root)
    matcher = file_pattern(dataset.files)
    for path in sorted(folder.glob(dataset.files.replace(ID, "*"))):
        found = matcher.fullmatch(path.relative_to(folder).as_posix())
        if found and not path.is_dir():
            yield found.group("id"), path


def file_pattern(files: str) -> re.Pattern[str]:
    parts = re.split(r"(\{id\}|\*\*/|\*\*|\*|\?)", files)
    return re.compile("".join(WILDCARDS.get(part, re.escape(part)) for part in parts))
