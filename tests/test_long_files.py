import math
import re
import shutil

import pandas as pd
import pytest

from labcatalog.exceptions import DataSourceError
from labcatalog.metadata.fixes import evidence
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project
from labcatalog.sources import load_datasets

WAVES = ("1", "2", "3")


def make_long(root):
    # The three parent files as one, rows shuffled so a wave's rows are not its file's first lines.
    frames = [
        pd.read_csv(root / "data" / f"parent_w{w}.csv", dtype=str, keep_default_na=False).assign(
            wave=w
        )
        for w in WAVES
    ]
    long = pd.concat(frames, ignore_index=True).fillna("").sample(frac=1, random_state=1)
    long.to_csv(root / "data" / "parent_long.csv", index=False)
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    for w in WAVES:
        old = f"path: data/parent_w{w}.csv,"
        assert old in text
        text = text.replace(old, "path: data/parent_long.csv, wave_column: wave,")
        listed = set(pd.read_csv(root / "maps" / f"parent_w{w}.csv", dtype=str)["column"])
        extra = [c for c in long.columns if c not in listed]
        with open(root / "maps" / f"parent_w{w}.csv", "a", encoding="utf-8", newline="") as f:
            f.writelines(f"{column},,\n" for column in extra)
    config.write_text(text, encoding="utf-8")
    return long.reset_index(drop=True)


def rounded(value):
    # Sums over shuffled rows differ in the last bits, so floats are compared to 9 places.
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v) for v in value]
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 9)
    return value


@pytest.fixture
def long_project(mock_project, tmp_path):
    wide = tmp_path / "wide"
    shutil.copytree(mock_project, wide)
    make_long(mock_project)
    return mock_project, wide


def test_a_long_file_gives_what_one_file_per_wave_gives(long_project):
    root, wide = long_project
    long_result, wide_result = run_catalog(root), run_catalog(wide)
    assert rounded(long_result.summary.model_dump()) == rounded(wide_result.summary.model_dump())

    def by_person(result, name):
        # parent_w3 repeats an ID, so rows are ordered by every column, not the ID alone.
        found = result.scores[name].assign(pid=result.datasets[name].frame["pid"])
        return found.sort_values([*found.columns]).reset_index(drop=True)

    for name in wide_result.scores:
        pd.testing.assert_frame_equal(by_person(long_result, name), by_person(wide_result, name))

    def problems(result):
        # Messages name their first few people in file order, which the shuffle changes.
        return sorted(
            (i.code, i.level, re.sub(r"\d{4}[PC]", "ID", i.message)) for i in result.report.issues
        )

    assert problems(long_result) == problems(wide_result)


def test_problems_point_at_the_line_in_the_shared_file(long_project):
    root, _ = long_project
    long = pd.read_csv(root / "data" / "parent_long.csv", dtype=str, keep_default_na=False)
    result = run_catalog(root)
    spaced = next(
        i
        for i in result.report.issues
        if i.code == "id_whitespace" and i.details["dataset"] == "parent_w1"
    )
    assert spaced.location == "data/parent_long.csv"
    (row,) = spaced.details["rows"]
    assert long.loc[row, "pid"] == " 1031P"
    assert long.loc[row, "wave"] == "1"
    shown = evidence(result.datasets["parent_w1"], spaced)
    assert shown == [{"row": str(row + 1), "id": "' 1031P'"}]


def test_a_wave_no_dataset_reads_is_reported(long_project):
    root, _ = long_project
    path = root / "data" / "parent_long.csv"
    long = pd.read_csv(path, dtype=str, keep_default_na=False)
    long.loc[long.index[:2], "wave"] = ["T3", ""]
    long.to_csv(path, index=False)
    (found,) = [i for i in run_catalog(root).report.issues if i.code == "wave_unclaimed"]
    assert found.level == "warning"
    assert found.location == "data/parent_long.csv"
    assert found.message == "wave has rows for wave(s) that no dataset reads: '', T3"


def test_a_missing_wave_column_stops_loading(long_project):
    root, _ = long_project
    path = root / "labcatalog.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("wave_column: wave", "wave_column: visit"),
        encoding="utf-8",
    )
    with pytest.raises(DataSourceError, match="parent_w1: no wave column 'visit'"):
        load_datasets(load_project(root))
