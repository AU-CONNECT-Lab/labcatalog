from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel

IdOp = Literal[
    "strip",
    "upper",
    "lower",
    "remove_prefix",
    "remove_suffix",
    "add_prefix",
    "add_suffix",
    "zero_pad",
    "regex_replace",
]


class IdRule(BaseModel):
    op: IdOp
    value: str | int | None = None
    replacement: str | None = None


def parse_id_rules(raw: list[str | dict[str, Any]]) -> list[IdRule]:
    raise NotImplementedError


def normalize_ids(ids: pd.Series, rules: list[IdRule]) -> pd.Series:
    raise NotImplementedError


def family_ids(ids: pd.Series, pattern: str) -> pd.Series:
    raise NotImplementedError


def load_exclusions(path: Path) -> set[str]:
    raise NotImplementedError
