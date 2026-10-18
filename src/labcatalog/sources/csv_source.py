from pathlib import Path

import pandas as pd

from labcatalog.config import DatasetConfig
from labcatalog.datalad.annex import fetch_advice, is_placeholder
from labcatalog.exceptions import DataSourceError
from labcatalog.paths import expand_path


class CsvSource:
    def read(self, dataset: DatasetConfig, project_root: Path, id_column: str) -> pd.DataFrame:
        return read_csv(expand_path(dataset.path, project_root), dataset.name)


def read_csv(path: Path, name: str) -> pd.DataFrame:
    if is_placeholder(path):
        raise DataSourceError(f"{name}: {fetch_advice(path)}")
    if not path.is_file():
        raise DataSourceError(f"{name}: data file not found: {path}")
    try:
        # Everything stays text so missing codes and blanks reach the checks unchanged.
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except UnicodeDecodeError:
        message = f"{name}: {path} is not UTF-8; in Excel save it as 'CSV UTF-8'"
        raise DataSourceError(message) from None
    except pd.errors.ParserError as err:
        raise DataSourceError(f"{name}: could not read {path}: {err}") from None
