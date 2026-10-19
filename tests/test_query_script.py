import shutil
import sqlite3
import subprocess
import sys
from glob import glob

import duckdb
import pytest

from labcatalog.metadata.stage_scripts import stage_script
from labcatalog.project import load_project

QUERY = "SELECT pid, visit, score FROM visits WHERE visit = 1 ORDER BY pid"
EXPECTED = ["pid,visit,score", "1001C,1,2.5", "1002C,1,"]


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


def r_has(*packages: str) -> bool:
    found = rscript()
    if found is None:
        return False
    test = " && ".join(f"requireNamespace('{p}', quietly = TRUE)" for p in packages)
    done = subprocess.run([found, "-e", f"quit(status = !({test}))"], capture_output=True)
    return done.returncode == 0


def fill(connection) -> None:
    connection.execute("CREATE TABLE visits (pid TEXT, visit INTEGER, score DOUBLE)")
    connection.execute(
        "INSERT INTO visits VALUES ('1002C', 1, NULL), ('1001C', 1, 2.5), ('1001C', 2, 3.0)"
    )


def sqlite_file(path):
    connection = sqlite3.connect(path)
    fill(connection)
    connection.commit()
    connection.close()
    return path


def written(mock_project, language: str, database: str) -> str:
    made = stage_script(load_project(mock_project), "database", language, database, "", "parent_w1")
    script = mock_project / made.path
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        made.text.replace("SELECT * FROM visits", QUERY), encoding="utf-8", newline="\n"
    )
    return made.path


def test_a_query_script_is_a_cleaning_step_for_the_dataset(mock_project):
    made = stage_script(
        load_project(mock_project), "database", "python", "db/tracker.db", "", "parent_w1"
    )
    assert made.path == "scripts/query_parent_w1.py"
    assert made.step.name == "query_parent_w1" and made.step.stage == "clean"
    assert made.step.run == "python scripts/query_parent_w1.py db/tracker.db data/parent_w1.csv"
    assert "Write QUERY" in made.text and "with the ID in pid" in made.text


@pytest.mark.parametrize("kind", ["sqlite", "duckdb"])
def test_the_python_query_script_writes_the_rows_as_csv(mock_project, kind):
    database = mock_project / "tracker.db"
    if kind == "sqlite":
        sqlite_file(database)
    else:
        with duckdb.connect(str(database)) as connection:
            fill(connection)
    script = written(mock_project, "python", "tracker.db")
    out = mock_project / "out.csv"
    subprocess.run([sys.executable, script, "tracker.db", str(out)], cwd=mock_project, check=True)
    assert out.read_text(encoding="utf-8").splitlines() == EXPECTED


@pytest.mark.skipif(not r_has("DBI", "RSQLite"), reason="R with DBI and RSQLite is not installed")
def test_the_r_query_script_reads_a_sqlite_file(mock_project):
    sqlite_file(mock_project / "tracker.db")
    script = written(mock_project, "r", "tracker.db")
    out = mock_project / "out.csv"
    subprocess.run([rscript(), script, "tracker.db", str(out)], cwd=mock_project, check=True)
    assert out.read_text(encoding="utf-8").splitlines() == [
        '"pid","visit","score"',
        '"1001C",1,2.5',
        '"1002C",1,',
    ]
