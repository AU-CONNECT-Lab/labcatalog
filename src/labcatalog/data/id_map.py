import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from labcatalog import defaults
from labcatalog.issues import Issue

COLUMNS = ["dataset", "from", "to"]
PREFIX = "prefix"
SUFFIX = "suffix"
REPLACE = "replace"
PAD = "pad"
TRIM = "trim"
UPPER = "upper"
LOWER = "lower"
RULES = {
    PREFIX: "Remove a prefix",
    SUFFIX: "Remove a suffix",
    REPLACE: "Find and replace",
    PAD: "Pad the number with zeros",
    TRIM: "Remove spaces",
    UPPER: "Upper case",
    LOWER: "Lower case",
}
DIGITS = re.compile(r"\d+")


@dataclass
class Rule:
    kind: str
    # The prefix, suffix or regular expression to find.
    text: str = ""
    replacement: str = ""
    width: int = 4


@dataclass
class Row:
    old: str
    new: str
    # None when there is no ids.pattern or no roster to hold the new ID to.
    matches: bool | None
    listed: bool | None
    # Another ID of the file becomes the same.
    clash: bool = False


def path_of(root: Path) -> Path:
    return root / defaults.ID_MAP_FILENAME


def read(root: Path) -> pd.DataFrame:
    path = path_of(root)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def mapping(root: Path, dataset: str) -> dict[str, str]:
    table = read(root)
    rows = table[table["dataset"] == dataset]
    return dict(zip(rows["from"], rows["to"], strict=True))


def apply(ids: pd.Series, found: dict[str, str]) -> pd.Series:
    return ids.map(lambda value: found.get(value, value))


def rewrite(value: str, rules: list[Rule]) -> str:
    for rule in rules:
        if rule.kind == PREFIX and rule.text:
            value = value.removeprefix(rule.text)
        elif rule.kind == SUFFIX and rule.text:
            value = value.removesuffix(rule.text)
        elif rule.kind == REPLACE and rule.text:
            value = re.sub(rule.text, rule.replacement, value)
        elif rule.kind == PAD:
            value = DIGITS.sub(lambda m, width=rule.width: m.group().zfill(width), value, count=1)
        elif rule.kind == TRIM:
            value = value.strip()
        elif rule.kind == UPPER:
            value = value.upper()
        elif rule.kind == LOWER:
            value = value.lower()
    return value


def rule_problem(rules: list[Rule]) -> str | None:
    for rule in rules:
        if rule.kind == REPLACE and rule.text:
            try:
                re.compile(rule.text)
            except re.error as err:
                return f"The pattern {rule.text!r} is not a regular expression: {err}."
    return None


def propose(
    ids: list[str],
    rules: list[Rule],
    manual: dict[str, str],
    pattern: str | None,
    roster: set[str] | None,
) -> list[Row]:
    # Each distinct ID of the file, its new ID by the rules unless typed by hand, and its checks.
    olds = list(dict.fromkeys(ids))
    news = {old: manual.get(old, rewrite(old, rules)) for old in olds}
    owners: dict[str, set[str]] = {}
    for old, new in news.items():
        owners.setdefault(new, set()).add(old)
    return [
        Row(
            old,
            new,
            bool(re.fullmatch(pattern, new)) if pattern else None,
            new in roster if roster is not None else None,
            len(owners[new]) > 1,
        )
        for old, new in news.items()
    ]


def save(root: Path, dataset: str, rows: list[Row]) -> int:
    # Replaces this dataset's entries for these IDs; an ID left as it is needs no entry.
    table = read(root)
    olds = {r.old for r in rows}
    kept = table[~((table["dataset"] == dataset) & table["from"].isin(olds))]
    added = pd.DataFrame(
        [{"dataset": dataset, "from": r.old, "to": r.new} for r in rows if r.new != r.old],
        columns=COLUMNS,
    )
    pd.concat([kept, added], ignore_index=True).to_csv(path_of(root), index=False)
    return len(added)


def check(root: Path, datasets: set[str]) -> list[Issue]:
    path = path_of(root)
    if not path.exists():
        return []
    table = read(root)
    where = defaults.ID_MAP_FILENAME
    issues = []
    if list(table.columns) != COLUMNS:
        message = f"{where} needs the columns {', '.join(COLUMNS)}"
        return [Issue(level="error", code="id_map_invalid", message=message, location=where)]
    for line, row in enumerate(table.itertuples(index=False), start=2):
        found = dict(zip(COLUMNS, row, strict=True))
        if found["dataset"] not in datasets:
            issues.append(
                Issue(
                    level="warning",
                    code="id_map_invalid",
                    message=f"{where} names a dataset labcatalog.yaml does not have: "
                    f"{found['dataset']}",
                    location=f"{where}:{line}",
                )
            )
        if not found["to"].strip():
            issues.append(
                Issue(
                    level="error",
                    code="id_map_invalid",
                    message=f"{where} gives {found['from']} no new ID",
                    location=f"{where}:{line}",
                )
            )
    repeated = table[table.duplicated(["dataset", "from"], keep=False)]
    for (dataset, old), _ in repeated.groupby(["dataset", "from"]):
        issues.append(
            Issue(
                level="error",
                code="id_map_invalid",
                message=f"{where} gives {old} in {dataset} more than one new ID",
                location=where,
            )
        )
    return issues
