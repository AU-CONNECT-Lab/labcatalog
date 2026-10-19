import uuid
from pathlib import Path

import duckdb
import pandas as pd

from labcatalog import defaults
from labcatalog.data import id_map
from labcatalog.exceptions import MetadataError
from labcatalog.pipeline import CatalogResult, run_catalog
from labcatalog.reports.export import data_frame, item_statistics, score_statistics, variable_rows
from labcatalog.sources.folder_source import folder_files

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
        "folder_files": pd.DataFrame(folder_file_rows(result)),
        "build": pd.DataFrame([build]),
    }


def folder_file_rows(result: CatalogResult) -> list[dict]:
    # Each file of a folder dataset, under its person's ID as corrected, to join with the data.
    root = result.project.root
    id_column = result.project.config.defaults.id_column
    rows = []
    for name, loaded in result.datasets.items():
        dataset = loaded.config
        if dataset.source != "folder":
            continue
        corrected = id_map.mapping(root, name)
        for file in folder_files(dataset, root):
            path = file.path.relative_to(root) if file.path.is_relative_to(root) else file.path
            rows.append(
                {
                    "dataset": name,
                    "study": dataset.study,
                    "wave": str(dataset.wave),
                    id_column: corrected.get(file.id, file.id),
                    "path": path.as_posix(),
                    "size": file.size,
                    "here": file.here,
                }
            )
    return rows


def write_database(result: CatalogResult, path: Path) -> Path:
    # Built beside the old file and swapped in, so a failed build keeps the last good one;
    # each build has its own partial file, so two people building at once do not collide.
    partial = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    date_format = result.project.config.defaults.date_format
    try:
        with duckdb.connect(str(partial)) as con:
            con.execute(f"CREATE SCHEMA {DATA_SCHEMA}")
            for name, instruments in full_plan(result).items():
                config = result.datasets[name].config
                frame = typed(
                    data_frame(result, name, instruments), config.date_column, date_format
                )
                write_table(con, f'{DATA_SCHEMA}."{name}"', frame)
            for name, frame in tables(result).items():
                # A project with nothing of a kind yet, such as no scores, has no table for it.
                if len(frame.columns):
                    write_table(con, name, frame)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
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
