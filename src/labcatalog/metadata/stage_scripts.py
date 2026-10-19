import textwrap
from dataclasses import dataclass

from labcatalog import defaults
from labcatalog.config import PrepareStep, dataset_by_name, id_column_for, missing_codes_for
from labcatalog.exceptions import EditError
from labcatalog.metadata.scripts import LANGUAGES, command
from labcatalog.project import Project

# Each stage's script: the function a person fills in, and the lines that apply it to the files.
BODIES = {
    ("clean", "python"): """\
import sys

import pandas as pd


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    data = raw.copy()
    # Rename columns, recode values and drop test rows here.
    return data


if __name__ == "__main__":
    clean(pd.read_csv(sys.argv[1])).to_csv(sys.argv[2], index=False)
""",
    ("clean", "r"): """\
clean <- function(raw) {
  data <- raw
  # Rename columns, recode values and drop test rows here.
  data
}

args <- commandArgs(trailingOnly = TRUE)
write.csv(clean(read.csv(args[1])), args[2], row.names = FALSE)
""",
    ("extract", "python"): """\
import sys
from pathlib import Path

import pandas as pd


def features(path: Path) -> dict:
    # One person's output: return their row, such as {"alpha_power": 1.2}.
    return {}


if __name__ == "__main__":
    folder, target = Path(sys.argv[1]), sys.argv[2]
    rows = []
    for path in sorted(folder.iterdir()):
        # The person's ID, here taken from the file's name.
        rows.append({"ID_COLUMN": path.stem, **features(path)})
    pd.DataFrame(rows).to_csv(target, index=False)
""",
    ("extract", "r"): """\
features <- function(path) {
  # One person's output: return their row, such as list(alpha_power = 1.2).
  list()
}

args <- commandArgs(trailingOnly = TRUE)
rows <- lapply(list.files(args[1], full.names = TRUE), function(path) {
  # The person's ID, here taken from the file's name.
  data.frame(ID_COLUMN = tools::file_path_sans_ext(basename(path)), features(path))
})
write.csv(do.call(rbind, rows), args[2], row.names = FALSE)
""",
    ("process", "python"): """\
import sys
from pathlib import Path


def process(recording: Path, out_dir: Path) -> None:
    # One person's raw recording: run the pipeline on it and write its output in out_dir.
    pass


if __name__ == "__main__":
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    target.mkdir(parents=True, exist_ok=True)
    for recording in sorted(source.iterdir()):
        process(recording, target)
""",
    ("database", "python"): '''\
import csv
import sqlite3
import sys
from pathlib import Path

QUERY = """
SELECT * FROM visits
"""


def connect(path: str):
    # Read only: a SQLite file starts with this header; any other file is read as DuckDB.
    with open(path, "rb") as file:
        if file.read(16) == b"SQLite format 3\\x00":
            return sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    import duckdb

    return duckdb.connect(path, read_only=True)


if __name__ == "__main__":
    connection = connect(sys.argv[1])
    rows = connection.execute(QUERY)
    with open(sys.argv[2], "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\\n")
        writer.writerow([d[0] for d in rows.description])
        writer.writerows(["" if v is None else v for v in row] for row in rows.fetchall())
    connection.close()
''',
    ("database", "r"): """\
library(DBI)

QUERY <- "
SELECT * FROM visits
"

args <- commandArgs(trailingOnly = TRUE)
# Read only: a SQLite file starts with this header; any other file is read as DuckDB.
sqlite <- identical(readBin(args[1], "raw", 15), charToRaw("SQLite format 3"))
connection <- if (sqlite) {
  dbConnect(RSQLite::SQLite(), args[1], flags = RSQLite::SQLITE_RO)
} else {
  dbConnect(duckdb::duckdb(), args[1], read_only = TRUE)
}
rows <- dbGetQuery(connection, QUERY)
dbDisconnect(connection)
out <- file(args[2], "wb")
write.csv(rows, out, row.names = FALSE, na = "")
close(out)
""",
    ("process", "r"): """\
process <- function(recording, out_dir) {
  # One person's raw recording: run the pipeline on it and write its output in out_dir.
}

args <- commandArgs(trailingOnly = TRUE)
dir.create(args[2], showWarnings = FALSE, recursive = TRUE)
for (recording in list.files(args[1], full.names = TRUE)) process(recording, args[2])
""",
}


@dataclass
class NewScript:
    path: str
    text: str
    step: PrepareStep


def stage_script(
    project: Project,
    stage: str,
    language: str,
    source: str,
    target: str = "",
    dataset: str | None = None,
    name: str = "",
) -> NewScript:
    # A clean, extract or database script writes a dataset's file; a process script writes a folder.
    if not source:
        raise EditError("Choose what the script reads")
    if dataset is not None:
        found = dataset_by_name(project.config, dataset)
        if not found.path:
            raise EditError(f"{dataset} reads a folder of files, so no script writes it")
        target, name = found.path, f"{NAME_STARTS.get(stage, stage)}_{dataset}"
    if not target or not name:
        raise EditError("Give the script a name and the folder it writes")
    path = f"{defaults.SCRIPTS_DIR}/{name}{LANGUAGES[language].suffix}"
    if (project.root / path).exists():
        raise EditError(f"{path} already exists")
    run = command(language, path, source, target)
    inputs = [source, path]
    lines = [f"labcatalog runs: {run}"]
    if dataset is not None:
        lines += dataset_lines(project, dataset)
    else:
        lines.append(f"It reads each recording in {source} and writes its output to {target}.")
    lines.append(FUNCTIONS[stage])
    header = "\n".join(
        f"# {part}" for line in lines for part in textwrap.wrap(line, 96, subsequent_indent="  ")
    )
    id_column = id_column_for(project.config, found) if dataset else ""
    body = BODIES[(stage, language)].replace("ID_COLUMN", id_column)
    step = PrepareStep(
        name=name, run=run, inputs=inputs, outputs=[target], stage=STEP_STAGES.get(stage, stage)
    )
    return NewScript(path, f"{header}\n\n{body}", step)


FUNCTIONS = {
    "clean": "Fill in clean(), which gets the raw export as a table and returns the clean table; "
    "the lines below it apply it to the files.",
    "extract": "Fill in features(), which gets one person's output and returns their row; "
    "the lines below it apply it to the files.",
    "process": "Fill in process(), which gets one person's recording and the folder to write to; "
    "the lines below it apply it to the files.",
    "database": "Write QUERY, whose rows become the file, one per person; the lines below it run "
    "it on the database, opened read only.",
}
# A query's step cleans: it turns the database into a dataset's file.
STEP_STAGES = {"database": "clean"}
NAME_STARTS = {"database": "query"}


def dataset_lines(project: Project, dataset: str) -> list[str]:
    config = project.config
    found = dataset_by_name(config, dataset)
    columns = [e.column for e in project.maps.get(found.map_name(), []) if e.instrument]
    codes = ", ".join(
        f"{c.code if str(c.code) else chr(34) * 2} = {c.label}"
        for c in missing_codes_for(config, found)
    )
    lines = [
        f"It writes {found.path}, the file of the dataset {dataset} ({found.study}, wave "
        f"{found.wave}, {found.reporter}, {found.modality}): one row per person, with the ID in "
        f"{id_column_for(config, found)}."
    ]
    if columns:
        lines.append(f"The columns its map ({found.map_file()}) names: {', '.join(columns)}.")
    if codes:
        lines.append(f"Missing codes: {codes}.")
    return lines
