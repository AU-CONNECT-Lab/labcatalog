import re
from collections import Counter
from pathlib import Path

import pandas as pd

from labcatalog.config import DatasetConfig
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


def file_pattern(files: str) -> re.Pattern[str]:
    parts = re.split(r"(\{id\}|\*\*/|\*\*|\*|\?)", files)
    return re.compile("".join(WILDCARDS.get(part, re.escape(part)) for part in parts))
