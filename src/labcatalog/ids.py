import csv
from pathlib import Path

import pandas as pd

from labcatalog.exceptions import DataSourceError


def group_ids(ids: pd.Series, pattern: str) -> pd.Series:
    return ids.str.extract(pattern, expand=False)


def load_exclusions(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise DataSourceError(f"Exclusion list not found: {path}") from None
    except UnicodeDecodeError:
        raise DataSourceError(f"{path} is not UTF-8; in Excel save it as 'CSV UTF-8'") from None
    reader = csv.DictReader(text.splitlines())
    if "id" not in (reader.fieldnames or []):
        raise DataSourceError(f"{path} needs a column named id")
    return {row["id"].strip() for row in reader if (row["id"] or "").strip()}
