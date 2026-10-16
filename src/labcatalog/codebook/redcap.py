import csv
import html
import io
import re
from dataclasses import dataclass
from pathlib import Path

from labcatalog.exceptions import CodebookError

# The dictionary downloaded from REDCap's web page and the one from its API name columns differently.
HEADERS = {
    "name": ("Variable / Field Name", "field_name"),
    "form": ("Form Name", "form_name"),
    "type": ("Field Type", "field_type"),
    "label": ("Field Label", "field_label"),
    "choices": ("Choices, Calculations, OR Slider Labels", "select_choices_or_calculations"),
    "validation": (
        "Text Validation Type OR Show Slider Number",
        "text_validation_type_or_show_slider_number",
    ),
    "min": ("Text Validation Min", "text_validation_min"),
    "max": ("Text Validation Max", "text_validation_max"),
}
FIXED_CHOICES = {"yesno": "1=Yes; 0=No", "truefalse": "1=True; 0=False"}
CHECKBOX_CHOICES = "0=Unchecked; 1=Checked"
# Calculations, uploads and descriptive text are not answers; sql lists keep their options elsewhere.
SKIPPED = {"calc", "file", "descriptive", "sql"}
SLIDER_RANGE = ("0", "100")
TAG = re.compile(r"<[^>]+>")


@dataclass
class Field:
    item: str
    form: str
    text: str
    type: str
    choices: str = ""
    min: str = ""
    max: str = ""
    # The instrument's name when the source gives one, such as a Qualtrics block.
    form_label: str = ""


def read_dictionary(path: Path) -> dict[str, Field]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise CodebookError(
            f"{path.name} is not UTF-8; download the data dictionary again"
        ) from None
    rows = list(csv.DictReader(io.StringIO(text)))
    header = rows[0].keys() if rows else []
    found = {}
    for key, names in HEADERS.items():
        name = next((n for n in names if n in header), None)
        if name is None:
            raise CodebookError(
                f"{path.name} is not a REDCap data dictionary: it has no '{names[0]}' column"
            )
        found[key] = name
    fields: dict[str, Field] = {}
    for row in rows:
        values = {key: (row[name] or "").strip() for key, name in found.items()}
        for column, field in fields_of(values):
            fields[column] = field
    return fields


def fields_of(row: dict[str, str]) -> list[tuple[str, Field]]:
    # Export column names to what they hold; a checkbox has one 0/1 column per option.
    name, form, kind = row["name"], row["form"], row["type"]
    text = plain(row["label"])
    if kind in SKIPPED or not name:
        return []
    if kind == "checkbox":
        return [
            (column, Field(column, form, f"{text}: {label}", "choice", CHECKBOX_CHOICES))
            for column, label in (
                (f"{name}___{re.sub(r'[^a-z0-9]', '_', code.lower())}", label)
                for code, label in options(row["choices"])
            )
        ]
    if kind in ("radio", "dropdown"):
        choices = "; ".join(f"{code}={label}" for code, label in options(row["choices"]))
        return [(name, Field(name, form, text, "choice", choices))]
    if kind in FIXED_CHOICES:
        return [(name, Field(name, form, text, "choice", FIXED_CHOICES[kind]))]
    validation = row["validation"]
    if kind == "slider":
        low, high = row["min"] or SLIDER_RANGE[0], row["max"] or SLIDER_RANGE[1]
        return [(name, Field(name, form, text, "number", min=low, max=high))]
    if kind == "text" and (validation == "integer" or validation.startswith("number")):
        return [(name, Field(name, form, text, "number", min=row["min"], max=row["max"]))]
    return [(name, Field(name, form, text, "text"))]


def options(choices: str) -> list[tuple[str, str]]:
    found = []
    for part in filter(None, (p.strip() for p in choices.split("|"))):
        code, _, label = (s.strip() for s in part.partition(","))
        # labcatalog separates choices with semicolons.
        found.append((code, plain(label).replace(";", ",")))
    return found


def plain(text: str) -> str:
    return " ".join(html.unescape(TAG.sub(" ", text)).split())


def form_name(form: str) -> str:
    return form.replace("_", " ").capitalize()
