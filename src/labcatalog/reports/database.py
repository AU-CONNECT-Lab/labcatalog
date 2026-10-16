from pathlib import Path

import duckdb
import pandas as pd

from labcatalog import defaults
from labcatalog.exceptions import MetadataError
from labcatalog.pipeline import CatalogResult, run_catalog
from labcatalog.reports.export import data_frame, item_statistics, score_statistics, variable_rows

DATA_SCHEMA = "data"


def full_plan(result: CatalogResult) -> dict[str, list[str]]:
    plan = {}
    for dataset in result.project.config.datasets:
        if dataset.name not in result.datasets:
            continue
        found = [v.instrument_id for v in result.catalog.variables_for(dataset.name)]
        found += [s.instrument_id for s in result.catalog.scores_for(dataset.name)]
        plan[dataset.name] = list(dict.fromkeys(found))
    return plan


def typed(frame: pd.DataFrame, date_column: str | None, date_format: str) -> pd.DataFrame:
    # A column of numbers becomes numeric; missing codes stay as the values they are.
    out = frame.replace("", None)
    for column in out:
        if column == date_column:
            out[column] = pd.to_datetime(out[column], format=date_format, errors="coerce").dt.date
            continue
        if out[column].dtype.kind in "biuf":
            continue
        numbers = pd.to_numeric(out[column], errors="coerce")
        if numbers.notna().sum() == out[column].notna().sum():
            out[column] = numbers
    return out


def tables(result: CatalogResult) -> dict[str, pd.DataFrame]:
    plan = full_plan(result)
    participants = {d.dataset: d.n_ids for d in result.summary.datasets}
    datasets = [
        {
            "dataset": d.name,
            "study": d.study,
            "wave": str(d.wave),
            "reporter": d.reporter,
            "modality": d.modality,
            "path": d.path,
            "rows": len(result.datasets[d.name].frame),
            "participants": participants.get(d.name),
        }
        for d in result.project.config.datasets
        if d.name in result.datasets
    ]
    manifest = result.manifest
    build = {
        "built_at": manifest.built_at,
        "tool_version": manifest.tool_version,
        "metadata_commit": manifest.metadata_commit,
    }
    return {
        "datasets": pd.DataFrame(datasets),
        "variables": pd.DataFrame(variable_rows(result, plan)),
        "score_statistics": pd.DataFrame(score_statistics(result, plan)),
        "item_statistics": pd.DataFrame(item_statistics(result, plan)),
        "files": pd.DataFrame([f.model_dump() for f in manifest.files]),
        "build": pd.DataFrame([build]),
    }


def write_database(result: CatalogResult, path: Path) -> Path:
    # Built beside the old file and swapped in, so a failed build keeps the last good one.
    partial = path.with_name(f"{path.name}.partial")
    partial.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    date_format = result.project.config.defaults.date_format
    with duckdb.connect(str(partial)) as con:
        con.execute(f"CREATE SCHEMA {DATA_SCHEMA}")
        for name, instruments in full_plan(result).items():
            config = result.datasets[name].config
            frame = typed(data_frame(result, name, instruments), config.date_column, date_format)
            write_table(con, f'{DATA_SCHEMA}."{name}"', frame)
        for name, frame in tables(result).items():
            write_table(con, name, frame)
    partial.replace(path)
    return path


def write_table(con: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame) -> None:
    con.register("frame", frame)
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM frame")
    con.unregister("frame")


def run_database(root: Path) -> Path:
    result = run_catalog(root)
    if result.project is None:
        raise MetadataError(result.report.issues)
    return write_database(result, result.project.root / defaults.DATABASE_FILE)
