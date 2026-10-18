import sqlite3
import sys

import duckdb
import pytest

from labcatalog.cli import main
from labcatalog.data.sql import query_to_csv
from labcatalog.exceptions import DataSourceError

QUERY = "SELECT pid, visit, score FROM visits WHERE visit = 1 ORDER BY pid"
EXPECTED = ["pid,visit,score", "1001C,1,2.5", "1002C,1,"]


def fill(connection) -> None:
    connection.execute("CREATE TABLE visits (pid TEXT, visit INTEGER, score DOUBLE)")
    connection.execute(
        "INSERT INTO visits VALUES ('1002C', 1, NULL), ('1001C', 1, 2.5), ('1001C', 2, 3.0)"
    )


@pytest.fixture
def query(tmp_path):
    path = tmp_path / "visits.sql"
    path.write_text(QUERY, encoding="utf-8")
    return path


def test_a_sqlite_query_is_written_as_csv(tmp_path, query):
    database = tmp_path / "tracker.db"
    connection = sqlite3.connect(database)
    fill(connection)
    connection.commit()
    connection.close()
    output = tmp_path / "data" / "visits.csv"
    assert query_to_csv(database, query, output) == 2
    assert output.read_text(encoding="utf-8").splitlines() == EXPECTED


def test_a_duckdb_query_is_written_as_csv(tmp_path, query):
    database = tmp_path / "results.duckdb"
    with duckdb.connect(str(database)) as connection:
        fill(connection)
    output = tmp_path / "visits.csv"
    assert query_to_csv(database, query, output) == 2
    assert output.read_text(encoding="utf-8").splitlines() == EXPECTED


def test_a_bad_query_names_the_file_and_the_database(tmp_path):
    database = tmp_path / "tracker.db"
    connection = sqlite3.connect(database)
    fill(connection)
    connection.commit()
    connection.close()
    query = tmp_path / "wrong.sql"
    query.write_text("SELECT * FROM nowhere", encoding="utf-8")
    with pytest.raises(DataSourceError, match="wrong.sql on tracker.db: no such table"):
        query_to_csv(database, query, tmp_path / "out.csv")
    with pytest.raises(DataSourceError, match="No database file"):
        query_to_csv(tmp_path / "missing.db", query, tmp_path / "out.csv")


def test_the_command_writes_the_file(tmp_path, query, monkeypatch, capsys):
    database = tmp_path / "tracker.db"
    connection = sqlite3.connect(database)
    fill(connection)
    connection.commit()
    connection.close()
    output = tmp_path / "visits.csv"
    monkeypatch.setattr(sys, "argv", ["labcatalog", "sql", str(database), str(query), str(output)])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code in (0, None)
    assert f"Wrote 2 rows to {output}" in capsys.readouterr().out
