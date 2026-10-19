import textwrap
from dataclasses import dataclass

from labcatalog import defaults
from labcatalog.config import (
    PrepareStep,
    dataset_by_name,
    id_column_for,
    id_pattern,
    missing_codes_for,
)
from labcatalog.exceptions import EditError
from labcatalog.metadata import folder_rules
from labcatalog.metadata.new_dataset import folder_files
from labcatalog.metadata.scripts import LANGUAGES, command
from labcatalog.paths import expand_path
from labcatalog.project import Project

# How a script finds each person's file in a folder, by a rule such as Add a data file suggests.
PYTHON_FILES = """\
# Each person's file within the folder: {id} where its path holds the ID, * for any part of a name.
FILES = "FILES_RULE"
"""
PYTHON_PERSON_FILES = """\
def person_files(folder: Path) -> list[tuple[str, Path]]:
    pattern = re.escape(FILES).replace(r"\\*", "[^/]*").replace(r"\\{id\\}", "(?P<id>[^/]+)")
    found = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if match := re.fullmatch(pattern, path.relative_to(folder).as_posix()):
            found.append((match["id"], path))
    return found
"""
R_FILES = """\
# Each person's file within the folder: {id} where its path holds the ID, * for any part of a name.
FILES <- "FILES_RULE"
"""
R_PERSON_FILES = """\
person_files <- function(folder) {
  pattern <- gsub("([][.+?^$()|\\\\\\\\])", "\\\\\\\\\\\\1", FILES, perl = TRUE)
  pattern <- gsub("*", "[^/]*", pattern, fixed = TRUE)
  pattern <- sub("{id}", "([^/]+)", pattern, fixed = TRUE)
  paths <- list.files(folder, recursive = TRUE)
  found <- regmatches(paths, regexec(paste0("^", pattern, "$"), paths))
  found <- Filter(length, found)
  data.frame(id = vapply(found, `[`, "", 2),
             path = file.path(folder, vapply(found, `[`, "", 1)))
}
"""

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
import re
import sys
from pathlib import Path

import pandas as pd

"""
    + PYTHON_FILES
    + """

def features(path: Path) -> dict:
    # One person's output: return their row, such as {"alpha_power": 1.2}.
    return {}


"""
    + PYTHON_PERSON_FILES
    + """

if __name__ == "__main__":
    folder, target = Path(sys.argv[1]), sys.argv[2]
    rows = [{"ID_COLUMN": person, **features(path)} for person, path in person_files(folder)]
    pd.DataFrame(rows).to_csv(target, index=False)
""",
    ("extract", "r"): R_FILES
    + """
features <- function(path) {
  # One person's output: return their row, such as list(alpha_power = 1.2).
  list()
}

"""
    + R_PERSON_FILES
    + """
args <- commandArgs(trailingOnly = TRUE)
files <- person_files(args[1])
rows <- lapply(seq_len(nrow(files)), function(i) {
  as.data.frame(c(list(ID_COLUMN = files$id[i]), features(files$path[i])))
})
write.csv(do.call(rbind, rows), args[2], row.names = FALSE)
""",
    ("process", "python"): """\
import re
import sys
from pathlib import Path

"""
    + PYTHON_FILES
    + """

def process(person: str, recording: Path, out_dir: Path) -> None:
    # One person's raw recording: run the pipeline on it and write its output in out_dir.
    pass


"""
    + PYTHON_PERSON_FILES
    + """

if __name__ == "__main__":
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    target.mkdir(parents=True, exist_ok=True)
    for person, recording in person_files(source):
        process(person, recording, target)
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
    ("process", "r"): R_FILES
    + """
process <- function(person, recording, out_dir) {
  # One person's raw recording: run the pipeline on it and write its output in out_dir.
}

"""
    + R_PERSON_FILES
    + """
args <- commandArgs(trailingOnly = TRUE)
dir.create(args[2], showWarnings = FALSE, recursive = TRUE)
files <- person_files(args[1])
for (i in seq_len(nrow(files))) process(files$id[i], files$path[i], args[2])
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
    files = EACH_FILE
    if stage in ("extract", "process"):
        files, line = person_rule(project, source, dataset)
        lines.append(line)
    lines.append(FUNCTIONS[stage])
    header = "\n".join(
        f"# {part}" for line in lines for part in textwrap.wrap(line, 96, subsequent_indent="  ")
    )
    id_column = id_column_for(project.config, found) if dataset else ""
    body = BODIES[(stage, language)].replace("ID_COLUMN", id_column).replace("FILES_RULE", files)
    step = PrepareStep(
        name=name, run=run, inputs=inputs, outputs=[target], stage=STEP_STAGES.get(stage, stage)
    )
    return NewScript(path, f"{header}\n\n{body}", step)


FUNCTIONS = {
    "clean": "Fill in clean(), which gets the raw export as a table and returns the clean table; "
    "the lines below it apply it to the files.",
    "extract": "Fill in features(), which gets one person's output and returns their row; "
    "the lines below it apply it to the files.",
    "process": "Fill in process(), which gets one person's ID, one of their recordings and the "
    "folder to write to; the lines below it apply it to each file FILES finds.",
    "database": "Write QUERY, whose rows become the file, one per person; the lines below it run "
    "it on the database, opened read only.",
}
# A query's step cleans: it turns the database into a dataset's file.
STEP_STAGES = {"database": "clean"}
NAME_STARTS = {"database": "query"}
# One file per person, named after the ID, when the folder suggests nothing else.
EACH_FILE = "{id}.*"


def person_rule(project: Project, source: str, dataset: str | None) -> tuple[str, str]:
    # The rule Add a data file would suggest for the folder: for the dataset's study and wave, or
    # with the project's ID pattern over every wave when the script writes no dataset.
    config = project.config
    found = dataset_by_name(config, dataset) if dataset else None
    folder = expand_path(source, project.root)
    paths = folder_files(folder) if folder.is_dir() else []
    pattern = id_pattern(config, found.study)[0] if found else config.ids.pattern
    wave = found.wave if found else ""
    key = folder_rules.id_field(folder_rules.path_fields(paths), pattern)
    rules = folder_rules.suggest(paths, key, wave, pattern) if key is not None else []
    if not rules:
        return EACH_FILE, (
            f"FILES below takes one file per person, named after the ID; {source} has no files "
            "yet, or none whose path holds an ID, so change it to fit the folder."
        )
    rule = rules[0]
    return rule.files, (
        f"FILES below is the rule that fits most of {source} now: {rule.people} people, "
        f"{rule.count} files."
    )


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
