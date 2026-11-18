from pathlib import Path

from ruamel.yaml.comments import CommentedMap

from labcatalog import defaults
from labcatalog.config import (
    DatasetConfig,
    PrepareStep,
    dataset_by_name,
    id_column_for,
    missing_codes_for,
)
from labcatalog.data.resolve import Catalog
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing, records
from labcatalog.paths import posix_str
from labcatalog.project import Project
from labcatalog.schema import SCRIPT

COMMANDS = {".r": "Rscript", ".py": "python"}
SUFFIXES = {"r": ".R", "python": ".py"}

R_TEMPLATE = """\
# Scores of {name} in {dataset}, for labcatalog: reads the data file, writes the scores file.
# {command}
# The scores file holds the ID column, then one column per score, named by the score's ID; leave
# a cell empty where a person has no score. Missing codes in this dataset: {codes}.
args <- commandArgs(trailingOnly = TRUE)
d <- read.csv(args[1], check.names = FALSE, colClasses = c({classes}))
{rows}scores <- data.frame(d[{id_text}], check.names = FALSE)
{blocks}
write.csv(scores, args[2], row.names = FALSE, na = "")
"""
PYTHON_TEMPLATE = """\
# Scores of {name} in {dataset}, for labcatalog: reads the data file, writes the scores file.
# {command}
# The scores file holds the ID column, then one column per score, named by the score's ID; leave
# a cell empty where a person has no score. Missing codes in this dataset: {codes}.
import sys

import pandas as pd

d = pd.read_csv(sys.argv[1], dtype={{{dtypes}}})
{rows}scores = pd.DataFrame({{{id_text}: d[{id_text}]}})
{blocks}
scores.to_csv(sys.argv[2], index=False)
"""


def step_name(instrument_id: str, dataset: str) -> str:
    return f"score_{instrument_id}_{dataset}"


def scores_path(instrument_id: str, dataset: str) -> str:
    return f"{defaults.DATA_DIR}/{dataset}_{instrument_id}_scores.csv"


def script_path(instrument_id: str, dataset: str, language: str) -> str:
    return f"{defaults.SCRIPTS_DIR}/{step_name(instrument_id, dataset)}{SUFFIXES[language]}"


def scoring_step(project: Project, instrument_id: str, dataset: str, script: str) -> PrepareStep:
    data = dataset_by_name(project.config, dataset).path
    if data is None:
        raise EditError(f"{dataset} reads a folder, so a script cannot add scores to it")
    command = COMMANDS.get(Path(script).suffix.lower())
    if command is None:
        raise EditError(f"{script}: a scoring script is an R (.R) or Python (.py) file")
    output = scores_path(instrument_id, dataset)
    quoted = [f'"{p}"' if " " in p else p for p in (script, data, output)]
    return PrepareStep(
        name=step_name(instrument_id, dataset),
        run=" ".join([command, *quoted]),
        inputs=[data, script],
        outputs=[output],
        stage="score",
    )


def registered(project: Project, instrument_id: str, dataset: str) -> PrepareStep | None:
    name = step_name(instrument_id, dataset)
    return next((s for s in project.config.prepare if s.name == name), None)


def register(project: Project, instrument_id: str, dataset: str, script: str) -> PrepareStep:
    # The step runs the script; the dataset reads the file it writes.
    step = scoring_step(project, instrument_id, dataset, script)
    editing.save_step(project.root, step)
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    entry = next(d for d in data["datasets"] if d["name"] == dataset)
    files = entry.get("scores") or CommentedMap()
    files[instrument_id] = step.outputs[0]
    files.fa.set_flow_style()
    entry["scores"] = files
    editing.save_data(project.root, opened, data)
    return step


def start_script(
    project: Project, catalog: Catalog, instrument_id: str, dataset: str, language: str
) -> str:
    # A script to fill in, unless one is already there.
    script = script_path(instrument_id, dataset, language)
    path = project.root / script
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template(project, catalog, instrument_id, dataset, language), "utf-8")
    return posix_str(Path(script))


def template(
    project: Project, catalog: Catalog, instrument_id: str, dataset: str, language: str
) -> str:
    config = project.config
    found = dataset_by_name(config, dataset)
    instrument = project.instruments[instrument_id]
    step = scoring_step(
        project, instrument_id, dataset, script_path(instrument_id, dataset, language)
    )
    columns = {
        v.item_id: v.column
        for v in catalog.variables_for(dataset)
        if v.instrument_id == instrument_id
    }
    scripted = [s for s in instrument.scores if s.method == SCRIPT] or instrument.scores
    blocks = []
    for score in scripted:
        used = [columns[i] for i in (score.items or list(columns)) if i in columns]
        reads = ", ".join(used) or "no columns of this dataset"
        empty = "NA" if language == "r" else "pd.NA"
        target = f'scores[["{score.id}"]]' if language == "r" else f'scores["{score.id}"]'
        blocks += ["", f"# {score.label} ({score.id}), from {reads}", f"{target} <- {empty}"]
    if language == "python":
        blocks = [line.replace(" <- ", " = ") for line in blocks]
    codes = ", ".join(f"{c.code} = {c.label}" for c in missing_codes_for(config, found)) or "none"
    id_column = id_column_for(config, found)
    text_columns = [f'"{c}"' for c in dict.fromkeys(filter(None, (id_column, found.wave_column)))]
    values = {
        "name": instrument.name,
        "dataset": dataset,
        "command": step.run,
        "codes": codes,
        "id": id_column,
        "id_text": f'"{id_column}"',
        "classes": ", ".join(f'{c} = "character"' for c in text_columns),
        "dtypes": ", ".join(f"{c}: str" for c in text_columns),
        "rows": wave_rows(found, language),
        "blocks": "\n".join(blocks),
    }
    return (R_TEMPLATE if language == "r" else PYTHON_TEMPLATE).format(**values)


def wave_rows(dataset: DatasetConfig, language: str) -> str:
    # A file of several waves gives this dataset only its own wave's rows, as labcatalog reads it.
    if not dataset.wave_column:
        return ""
    column, wave = dataset.wave_column, dataset.wave_in_file()
    note = (
        f"# The data file holds several waves; {dataset.name} is its rows with {column} {wave}.\n"
    )
    if language == "r":
        return note + f'd <- d[d[["{column}"]] %in% "{wave}", , drop = FALSE]\n'
    return note + f'd = d[d["{column}"] == "{wave}"]\n'
