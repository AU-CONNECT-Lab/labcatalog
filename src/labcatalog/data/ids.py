import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from labcatalog.datalad.annex import fetch_advice, is_placeholder
from labcatalog.exceptions import DataSourceError


def group_ids(ids: pd.Series, pattern: str) -> pd.Series:
    return ids.str.extract(pattern, expand=False)


@dataclass
class Exclusions:
    people: set[str]
    groups: set[str]


def load_exclusions(path: Path) -> Exclusions:
    if is_placeholder(path):
        raise DataSourceError(f"Exclusion list: {fetch_advice(path)}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise DataSourceError(f"Exclusion list not found: {path}") from None
    except UnicodeDecodeError:
        raise DataSourceError(f"{path} is not UTF-8; in Excel save it as 'CSV UTF-8'") from None
    reader = csv.DictReader(text.splitlines())
    if not {"id", "group"} & set(reader.fieldnames or []):
        raise DataSourceError(f"{path} needs a column named id, group or both")
    rows = list(reader)

    def listed(column: str) -> set[str]:
        return {v.strip() for row in rows if (v := row.get(column) or "").strip()}

    return Exclusions(listed("id"), listed("group"))
