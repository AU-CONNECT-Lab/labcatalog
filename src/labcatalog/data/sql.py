import csv
import sqlite3
from pathlib import Path
from typing import Any

import duckdb

from labcatalog.exceptions import DataSourceError

SQLITE_HEADER = b"SQLite format 3\x00"


def query_to_csv(database: Path, query_file: Path, output: Path) -> int:
    try:
        query = query_file.read_text(encoding="utf-8")
    except OSError as err:
        raise DataSourceError(f"Cannot read {query_file}: {err}") from None
    if not database.is_file():
        raise DataSourceError(f"No database file {database}")
    try:
        columns, rows = run_query(database, query)
    except (sqlite3.Error, duckdb.Error) as err:
        raise DataSourceError(f"{query_file.name} on {database.name}: {err}") from None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(["" if value is None else value for value in row] for row in rows)
    return len(rows)


def run_query(database: Path, query: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    # Read only: SQLite through the standard library, anything else as a DuckDB file.
    with database.open("rb") as file:
        sqlite = file.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    if sqlite:
        connection = sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)
        try:
            cursor = connection.execute(query)
            return [d[0] for d in cursor.description], cursor.fetchall()
        finally:
            connection.close()
    with duckdb.connect(str(database), read_only=True) as connection:
        result = connection.execute(query)
        return [d[0] for d in result.description], result.fetchall()
