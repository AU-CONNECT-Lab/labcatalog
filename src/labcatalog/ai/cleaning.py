import difflib
import itertools
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from labcatalog import defaults
from labcatalog.config import (
    PrepareStep,
    dataset_by_name,
    id_column_for,
    id_pattern,
    missing_codes_for,
)
from labcatalog.data.resolve import Catalog, ResolvedVariable, as_text_dict
from labcatalog.exceptions import DataSourceError
from labcatalog.issues import Issue
from labcatalog.llm import CallMetadata, LLMClient, ToolSchema
from labcatalog.metadata.editing import save_step
from labcatalog.metadata.scripts import LANGUAGES, command, language_of
from labcatalog.metadata.validate import same_file
from labcatalog.paths import posix_str
from labcatalog.project import Project

DRAFT_SYSTEM = """You write data cleaning scripts for research projects. You are given a raw \
export and the clean file the project reads: its columns, what each column holds and the values \
each may take. Write one {language} script that reads the raw file and writes the clean file.

The script takes two arguments, the raw file and the clean file ({usage}). It reads only the raw \
file and writes only the clean file, never over the raw file, and uses only {libraries}.

Keep every row that is a real response, and drop rows that are not, such as extra header rows, \
previews or test runs; say in the notes which rules decide this. Write the columns the clean file \
lists, under those names and in that order. Recode answers written as labels into the option \
values listed. Keep the missing codes as they are, and leave a cell blank where an answer is \
missing. Leave IDs as they are typed unless a rule given here says otherwise, since the project \
checks them. Start each part of the script with a comment saying what it does.

In the notes, list each decision the raw file did not settle, and anything in it that disagrees \
with the clean file, such as a column you could not find. Leave the notes empty when there is \
nothing to report. Leave the changes empty."""

FIX_SYSTEM = """You revise data cleaning scripts for research projects. You are given a \
{language} script, the raw file it reads, the clean file it writes, and a problem the project \
found in the clean file, with the rows it is about. Change the script so the clean file no longer \
has the problem, and change nothing else.

Return the whole revised script, keeping its arguments, the files it reads and writes, and its \
style; it still uses only {libraries}. In the changes, say what you changed, one line each. In \
the notes, list each decision the problem did not settle, such as which of two rows to keep, or \
say that the script cannot fix it, such as an ID only the people who collected the data can \
correct. Leave the notes empty when there is nothing to report."""

SCHEMA = ToolSchema(
    name="cleaning_script",
    description="A cleaning script, what changed in it, and what it left open.",
    input_schema={
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "The whole script."},
            "changes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What changed in a revised script, one line each.",
            },
            "notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Decisions left open, and disagreements.",
            },
        },
        "required": ["script", "changes", "notes"],
        "additionalProperties": False,
    },
)


# What the language model sees of the raw file: each column's values, or its first lines.
VALUES = "values"
ROWS = "rows"
RAW_ROWS = 20
SHOWN_VALUES = 30


@dataclass
class CleaningDraft:
    dataset: str
    script_path: str
    script: str
    # The script as it was, when the draft revises one.
    previous: str | None
    # The step to register, when the draft is a new script.
    step: PrepareStep | None
    meta: CallMetadata
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def diff(self) -> str:
        lines = difflib.unified_diff(
            (self.previous or "").splitlines(),
            self.script.splitlines(),
            "before",
            "after",
            lineterm="",
        )
        return "\n".join(lines)


def cleaning_step(project: Project, dataset: str) -> PrepareStep | None:
    # The step that writes this dataset's file with a script the model can revise.
    path = dataset_by_name(project.config, dataset).path
    if path is None:
        return None
    target = same_file(project, path)
    for step in project.config.prepare:
        if target in {same_file(project, p) for p in step.outputs} and script_of(step):
            return step
    return None


def script_of(step: PrepareStep) -> str | None:
    return next((p for p in step.inputs if language_of(p)), None)


def raw_of(step: PrepareStep) -> str | None:
    return next((p for p in step.inputs if not language_of(p)), None)


def usage(language: str) -> str:
    lang = LANGUAGES[language]
    return f"{lang.command} script{lang.suffix} <raw> <clean>, read with {lang.arguments}"


def clean_file_lines(project: Project, catalog: Catalog, dataset: str) -> list[str]:
    config = project.config
    found = dataset_by_name(config, dataset)
    variables = {v.column: v for v in catalog.variables_for(dataset)}
    roles = {
        id_column_for(config, found): "the ID of the person the row is about",
        found.respondent_column: "the ID of whoever filled in the row",
        found.date_column: f"the date, written {config.defaults.date_format}",
        found.wave_column: "the wave of the row",
    }
    lines = [
        f"Clean file: {found.path}",
        "Its columns, in order (column | what it holds | values):",
    ]
    for entry in project.maps.get(found.map_name(), []):
        if entry.column in variables:
            lines.append(item_line(project, variables[entry.column]))
        else:
            lines.append(f"{entry.column} | {roles.get(entry.column, 'kept as it is')} |")
    codes = missing_codes_for(config, found)
    listed = ", ".join(f"{c.code} = {c.label}" for c in codes) or "none"
    lines.append(f"Missing codes: {listed}")
    pattern, _ = id_pattern(config, found.study)
    if pattern:
        lines.append(f"IDs match the regular expression {pattern}")
    return lines


def item_line(project: Project, v: ResolvedVariable) -> str:
    instrument = project.instruments[v.instrument_id]
    text = " / ".join(as_text_dict(v.text).values())
    return f"{v.column} | {instrument.name}, {v.item_id}: {text} | {values_of(v)}"


def values_of(v: ResolvedVariable) -> str:
    if v.type == "choice":
        return "options " + ", ".join(f"{o.value} = {o.label}" for o in v.response_options)
    if v.type == "number":
        bounds = [
            f"{word} {x:g}"
            for word, x in (("min", v.allowed_min), ("max", v.allowed_max))
            if x is not None
        ]
        return " ".join(["number", *bounds])
    return v.type


def raw_lines(root: Path, raw: str, shown: str) -> list[str]:
    path = root / raw
    try:
        if shown == ROWS:
            with path.open(encoding="utf-8-sig", errors="replace") as file:
                head = [line.rstrip("\r\n") for line in itertools.islice(file, RAW_ROWS + 1)]
            return [f"Raw file: {raw}, its first lines:", "<raw>", *head, "</raw>"]
        frame = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as err:
        raise DataSourceError(f"{raw}: cannot read it as a CSV file: {err}") from err
    lines = [
        f"Raw file: {raw}, {len(frame)} rows under its header.",
        "Each column and the different values in it, in the order they first appear:",
    ]
    for column in frame.columns:
        values = list(dict.fromkeys(frame[column]))
        listed = ", ".join(repr(v) for v in values[:SHOWN_VALUES])
        more = len(values) - SHOWN_VALUES
        lines.append(f"{column}: {listed}" + (f" and {more} more" if more > 0 else ""))
    return lines


def draft_request(project: Project, catalog: Catalog, dataset: str, raw: str, shown: str) -> str:
    return "\n".join(
        [*raw_lines(project.root, raw, shown), "", *clean_file_lines(project, catalog, dataset)]
    )


def fix_request(
    project: Project, catalog: Catalog, issue: Issue, rows: list[dict[str, str]], shown: str
) -> str:
    dataset = issue.details["dataset"]
    step = cleaning_step(project, dataset)
    script = script_of(step)
    lines = [
        f"Script: {script}",
        "<script>",
        (project.root / script).read_text("utf-8"),
        "</script>",
    ]
    if raw := raw_of(step):
        lines += ["", *raw_lines(project.root, raw, shown)]
    lines += ["", *clean_file_lines(project, catalog, dataset), "", f"Problem: {issue.message}"]
    if rows:
        lines.append("The rows it is about, counting from the first line under the header:")
        lines += [", ".join(f"{k} {v}" for k, v in row.items()) for row in rows]
    return "\n".join(lines)


def draft_script(
    project: Project,
    catalog: Catalog,
    dataset: str,
    raw: str,
    language: str,
    client: LLMClient,
) -> CleaningDraft:
    lang = LANGUAGES[language]
    system = DRAFT_SYSTEM.format(
        language=lang.name, usage=usage(language), libraries=lang.libraries
    )
    request = draft_request(project, catalog, dataset, raw, project.config.llm.raw_data)
    output, meta = client.complete_structured(
        system=system, user_message=request, tool_schema=SCHEMA
    )
    clean = dataset_by_name(project.config, dataset).path
    script = posix_str(Path(defaults.SCRIPTS_DIR) / f"clean_{dataset}{lang.suffix}")
    header = [
        f"# Cleans {raw} into {clean}: drafted by {meta.provider} {meta.model} on "
        f"{date.today().isoformat()}. Check it before using it.",
        f"# {command(language, script, raw, clean)}",
        *(["# Notes from the model:"] if output["notes"] else []),
        *[f"# - {line}" for line in output["notes"]],
    ]
    step = PrepareStep(
        name=f"clean_{dataset}",
        run=command(language, script, raw, clean),
        inputs=[raw, script],
        outputs=[clean],
        stage="clean",
    )
    text = "\n".join(header) + "\n\n" + output["script"].strip() + "\n"
    return CleaningDraft(dataset, script, text, None, step, meta, [], output["notes"])


def fix_script(
    project: Project,
    catalog: Catalog,
    issue: Issue,
    rows: list[dict[str, str]],
    client: LLMClient,
) -> CleaningDraft:
    script = script_of(cleaning_step(project, issue.details["dataset"]))
    lang = LANGUAGES[language_of(script)]
    system = FIX_SYSTEM.format(language=lang.name, libraries=lang.libraries)
    request = fix_request(project, catalog, issue, rows, project.config.llm.raw_data)
    output, meta = client.complete_structured(
        system=system, user_message=request, tool_schema=SCHEMA
    )
    previous = (project.root / script).read_text("utf-8")
    text = output["script"].strip() + "\n"
    return CleaningDraft(
        issue.details["dataset"],
        script,
        text,
        previous,
        None,
        meta,
        output["changes"],
        output["notes"],
    )


def save_draft(root: Path, draft: CleaningDraft) -> None:
    path = root / draft.script_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft.script, encoding="utf-8")
    if draft.step is not None:
        save_step(root, draft.step)
