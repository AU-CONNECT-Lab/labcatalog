import re
from collections import Counter
from pathlib import Path

import pyreadstat

from labcatalog.exceptions import CodebookError
from labcatalog.redcap import Field


def read_sav(path: Path) -> dict[str, Field]:
    try:
        _, meta = pyreadstat.read_sav(path, metadataonly=True, user_missing=True)
    except (pyreadstat.ReadstatError, pyreadstat.PyreadstatError):
        raise CodebookError(f"{path.name} is not an SPSS data file (.sav)") from None
    # SPSS has no forms, so columns sharing a prefix are a guess at one instrument.
    prefixes = Counter(prefix(column) for column in meta.column_names)
    fields = {}
    for column in meta.column_names:
        # Labelled missing-value codes, such as -99 = Refused, are not options.
        missing = meta.missing_ranges.get(column, [])
        labels = {
            value: label
            for value, label in meta.variable_value_labels.get(column, {}).items()
            if not any(r["lo"] <= value <= r["hi"] for r in missing)
        }
        fields[column] = Field(
            item=column.lower(),
            form=prefix(column) if prefixes[prefix(column)] > 1 else "",
            text=" ".join((meta.column_names_to_labels.get(column) or "").split()),
            type=kind(meta.original_variable_types[column], labels),
            choices="; ".join(f"{code(v)}={label.replace(';', ',')}" for v, label in labels.items()),
        )
    return fields


def kind(spss_format: str, labels: dict) -> str:
    if spss_format.startswith("A"):
        return "text"
    return "choice" if labels else "number"


def code(value: float | str) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def prefix(column: str) -> str:
    found = re.match(r"[A-Za-z]+", column)
    return found.group().lower() if found else ""
