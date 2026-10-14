from pathlib import Path

import pandas as pd

from labcatalog.config import DatasetConfig


class CsvSource:
    def read(self, dataset: DatasetConfig, project_root: Path) -> pd.DataFrame:
        raise NotImplementedError
