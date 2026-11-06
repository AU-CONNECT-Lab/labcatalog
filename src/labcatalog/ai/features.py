from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from labcatalog import defaults
from labcatalog.ai.cleaning import raw_lines
from labcatalog.ai.code import unfenced
from labcatalog.ai.instrument import OPTIONAL, STRING, array, given, strict
from labcatalog.codebook.core import yaml_text
from labcatalog.config import PrepareStep, dataset_by_name
from labcatalog.exceptions import DataSourceError, EditError
from labcatalog.llm import CallMetadata, LLMClient, ToolSchema
from labcatalog.metadata.editing import free_instrument_path, save_step
from labcatalog.metadata.scripts import LANGUAGES
from labcatalog.metadata.stage_scripts import FEATURES, summary_script
from labcatalog.paths import portable_path, posix_str
from labcatalog.project import Project
from labcatalog.sources.folder_source import folder_files

SYSTEM = """You write one step of a research project's data pipeline: a {language} function \
that reads one person's file from a task or a recording, such as the trials of a computer task, \
and returns that person's measures. You are given one person's file and the measures the \
researcher wants.

Write only the function `{signature}`. It gets the path of one person's file and returns \
{returns} with one entry per measure, named in lower case with underscores. When a measure \
cannot be computed for this person, such as for a block they did not finish, it is {missing}. \
The script around the function already finds each person's file, adds their ID and writes the \
table, so do not write those parts. Use only {libraries}; {imports} Start each part of the \
function with a comment saying what it does.

Describe each measure the function returns as an item of the instrument the measures make up: \
its name exactly as the function returns it, a short label, what it is with its unit, and the \
lowest and highest values it can take when these are fixed, such as 0 and 1 for a share. Give \
the instrument a name and the construct it measures, and describe the task or recording as far \
as the file and the request show it.

In the notes, list each decision the file and the request did not settle, such as which rows \
are practice trials or how a trial with no response counts. Leave the notes empty when there is \
nothing to report."""

FUNCTIONS = {
    "python": {
        "signature": "def features(path: Path) -> dict:",
        "returns": "a dict",
        "missing": "None",
        "imports": "the script imports re, sys, Path from pathlib and pandas as pd, so import "
        "anything else inside the function.",
    },
    "r": {
        "signature": "features <- function(path)",
        "returns": "a named list",
        "missing": "NA",
        "imports": "do not call library().",
    },
}

SCHEMA = ToolSchema(
    name="summary_step",
    description="The features function, the instrument its measures make up, and what is open.",
    input_schema=strict(
        {
            "function": {"type": "string", "description": "The whole function and nothing else."},
            "name": {"type": "string", "description": "The instrument's name."},
            "construct_name": OPTIONAL,
            "description": OPTIONAL,
            "items": array(
                strict(
                    {
                        "id": {
                            "type": "string",
                            "description": "The measure's name, exactly as the function returns it.",
                        },
                        "label": STRING,
                        "text": {"type": "string", "description": "What it is, with its unit."},
                        "min": {"type": "string", "description": "Empty when it is not fixed."},
                        "max": {"type": "string", "description": "Empty when it is not fixed."},
                    }
                )
            ),
            "notes": array(STRING),
        }
    ),
)


@dataclass
class SummaryDraft:
    script_path: str
    script: str
    step: PrepareStep
    instrument_path: str
    instrument: str
    # The person's file the model was shown.
    sample: str
    meta: CallMetadata
    notes: list[str]


def sample_file(project: Project, files: str) -> str:
    # The largest file on this computer, likely a full session rather than one cut short.
    found = [
        f for f in folder_files(dataset_by_name(project.config, files), project.root) if f.here
    ]
    if not found:
        raise DataSourceError(f"{files}: none of its files is on this computer")
    largest = max(found, key=lambda f: f.size)
    return posix_str(portable_path(largest.path, project.root))


def summary_request(project: Project, files: str, sample: str, wanted: str) -> str:
    folder = dataset_by_name(project.config, files)
    return "\n".join(
        [
            f"The files: one per person in {folder.path}, found by the rule {folder.files}, "
            f"where {{id}} is the person's ID ({folder.modality}, study {folder.study}, wave "
            f"{folder.wave}, {folder.reporter}).",
            *raw_lines(project.root, sample, project.config.llm.raw_data, "One person's file"),
            "",
            "The measures wanted:",
            wanted.strip(),
        ]
    )


def draft_summary(
    project: Project,
    files: str,
    name: str,
    instrument_id: str,
    wanted: str,
    language: str,
    client: LLMClient,
) -> SummaryDraft:
    if not wanted.strip():
        raise EditError("Say which measures to compute")
    root = project.root
    free_instrument_path(root, instrument_id)
    made = summary_script(project, files, name, language)
    sample = sample_file(project, files)
    lang = LANGUAGES[language]
    system = SYSTEM.format(language=lang.name, libraries=lang.libraries, **FUNCTIONS[language])
    output, meta = client.complete_structured(
        system=system,
        user_message=summary_request(project, files, sample, wanted),
        tool_schema=SCHEMA,
    )
    notes = [" ".join(line.split()) for line in output["notes"]]
    header = [
        f"# features() was drafted by {meta.provider} {meta.model} on {date.today().isoformat()} "
        f"from {sample}; check it before running the step.",
        *(["# Notes from the model:"] if notes else []),
        *[f"# - {line}" for line in notes],
    ]
    function = unfenced(output["function"]).strip() + "\n"
    script = "\n".join(header) + "\n" + made.text.replace(FEATURES[language], function)
    instrument = posix_str(Path(defaults.DRAFTS_DIR) / f"{instrument_id}.yaml")
    text = instrument_text(instrument_id, dataset_by_name(project.config, files).modality, output)
    lines = [
        text.split("\n", 1)[0],
        f"# Drafted by {meta.provider} {meta.model} on {date.today().isoformat()} with "
        f"{made.path}: its items are the measures features() returns.",
        "# Check it against the script, then move it to instruments/.",
        text.split("\n", 1)[1].rstrip("\n"),
    ]
    return SummaryDraft(
        made.path, script, made.step, instrument, "\n".join(lines) + "\n", sample, meta, notes
    )


def instrument_text(instrument_id: str, modality: str, output: dict[str, Any]) -> str:
    document: dict[str, Any] = {"id": instrument_id, "name": output["name"].strip()}
    document["modality"] = modality
    document |= given({k: output[k] for k in ("construct_name", "description")})
    document["items"] = [
        {"id": i["id"].strip(), "label": i["label"].strip(), "text": i["text"].strip()}
        | {"type": "number"}
        | given({"min": i["min"], "max": i["max"]}, number=True)
        for i in output["items"]
    ]
    return yaml_text(document, "instrument")


def save_summary(root: Path, draft: SummaryDraft) -> None:
    (root / draft.script_path).parent.mkdir(parents=True, exist_ok=True)
    (root / draft.script_path).write_text(draft.script, encoding="utf-8")
    save_step(root, draft.step)
    (root / draft.instrument_path).parent.mkdir(exist_ok=True)
    (root / draft.instrument_path).write_text(draft.instrument, encoding="utf-8")
