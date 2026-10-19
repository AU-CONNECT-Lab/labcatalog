import re
from collections import Counter
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
        matcher = file_pattern(dataset.files)
        counts: Counter[str] = Counter()
        for path in folder.glob(dataset.files.replace(ID, "*")):
            found = matcher.fullmatch(path.relative_to(folder).as_posix())
            if found and not path.is_dir():
                counts[found.group("id")] += 1
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


def folder_size(dataset: DatasetConfig, project_root: Path) -> FolderSize:
    # The files the dataset's rule matches, as the catalog counts them.
    folder = expand_path(dataset.path, project_root)
    matcher = file_pattern(dataset.files)
    found = FolderSize()
    for path in folder.glob(dataset.files.replace(ID, "*")):
        if path.is_dir() or not matcher.fullmatch(path.relative_to(folder).as_posix()):
            continue
        found.files += 1
        if is_placeholder(path):
            size = annexed_size(path)
            found.unknown += size is None
            found.size += size or 0
        else:
            size = path.stat().st_size
            found.size += size
            found.here += 1
            found.here_size += size
    return found


def file_pattern(files: str) -> re.Pattern[str]:
    parts = re.split(r"(\{id\}|\*\*/|\*\*|\*|\?)", files)
    return re.compile("".join(WILDCARDS.get(part, re.escape(part)) for part in parts))
