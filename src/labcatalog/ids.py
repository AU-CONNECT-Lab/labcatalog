import csv
import re
from pathlib import Path
from typing import Any, Literal, get_args

import pandas as pd
from pydantic import BaseModel

from labcatalog.exceptions import DataSourceError

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

BARE_OPS = ("strip", "upper", "lower")


class IdRule(BaseModel):
    op: IdOp
    value: str | int | None = None
    replacement: str | None = None


def parse_id_rules(raw: list[str | dict[str, Any]]) -> tuple[list[IdRule], list[str]]:
    rules, problems = [], []
    for n, entry in enumerate(raw, start=1):
        rule = parse_id_rule(entry)
        if isinstance(rule, IdRule):
            rules.append(rule)
        else:
            problems.append(f"rule {n}: {rule}")
    return rules, problems


def parse_id_rule(entry: str | dict[str, Any]) -> IdRule | str:
    if isinstance(entry, str):
        if entry in BARE_OPS:
            return IdRule(op=entry)
        return f"'{entry}' is not one of {', '.join(BARE_OPS)}; other rules need a value"
    if not isinstance(entry, dict) or len(entry) != 1:
        return "write each rule as a name or as {name: value}"
    ((op, value),) = entry.items()
    if op not in get_args(IdOp) or op in BARE_OPS:
        return f"unknown rule '{op}'"
    if op == "zero_pad":
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            return "zero_pad needs a positive whole number"
        return IdRule(op=op, value=value)
    if op == "regex_replace":
        if not isinstance(value, dict) or set(value) != {"pattern", "replacement"}:
            return "regex_replace needs {pattern: ..., replacement: ...}"
        try:
            re.compile(value["pattern"])
        except re.error as err:
            return f"regex_replace pattern is invalid: {err}"
        return IdRule(op=op, value=value["pattern"], replacement=str(value["replacement"]))
    if not isinstance(value, str) or not value:
        return f"{op} needs some text"
    return IdRule(op=op, value=value)


def normalize_ids(ids: pd.Series, rules: list[IdRule]) -> pd.Series:
    ids = ids.astype(str)
    for rule in rules:
        ids = apply_rule(ids, rule)
    return ids


def apply_rule(ids: pd.Series, rule: IdRule) -> pd.Series:
    text = ids.str
    if rule.op == "strip":
        return text.strip()
    if rule.op == "upper":
        return text.upper()
    if rule.op == "lower":
        return text.lower()
    if rule.op == "remove_prefix":
        return text.removeprefix(rule.value)
    if rule.op == "remove_suffix":
        return text.removesuffix(rule.value)
    # Adding only where the affix is missing makes the rule safe on mixed files.
    if rule.op == "add_prefix":
        return ids.where(text.startswith(rule.value), rule.value + ids)
    if rule.op == "add_suffix":
        return ids.where(text.endswith(rule.value), ids + rule.value)
    if rule.op == "zero_pad":
        return text.zfill(rule.value)
    return text.replace(rule.value, rule.replacement, regex=True)


def family_ids(ids: pd.Series, pattern: str) -> pd.Series:
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
