import math
import re
import shutil

import pandas as pd
import pytest

from labcatalog.exceptions import DataSourceError
from labcatalog.metadata import changes, new_dataset
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
    # What the Fix offers to add: the blank wave cannot be one.
    assert (found.details["dataset"], found.details["waves"]) == ("parent_w3", ["T3"])


def test_a_missing_wave_column_stops_loading(long_project):
    root, _ = long_project
    path = root / "labcatalog.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("wave_column: wave", "wave_column: visit"),
        encoding="utf-8",
    )
    with pytest.raises(DataSourceError, match="parent_w1: no wave column 'visit'"):
        load_datasets(load_project(root))


def write_waves_as(root, written):
    # The long file names its waves another way, and each dataset says which one is its own.
    path = root / "data" / "parent_long.csv"
    long = pd.read_csv(path, dtype=str, keep_default_na=False)
    long["wave"] = long["wave"].map(written)
    long.to_csv(path, index=False)
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    for wave, value in written.items():
        old = "path: data/parent_long.csv, wave_column: wave,"
        line = next(x for x in text.splitlines() if f"name: parent_w{wave}," in x)
        text = text.replace(line, line.replace(old, f"{old} wave_value: {value},"))
    config.write_text(text, encoding="utf-8")
    return long


def test_a_wave_written_another_way_reads_its_own_rows(long_project):
    root, wide = long_project
    write_waves_as(root, {w: f"T{w}" for w in WAVES})
    long_result, wide_result = run_catalog(root), run_catalog(wide)
    assert rounded(long_result.summary.model_dump()) == rounded(wide_result.summary.model_dump())
    assert not [i for i in long_result.report.issues if i.code == "wave_unclaimed"]
    assert long_result.datasets["parent_w2"].config.wave == "2"


def test_a_wave_value_no_dataset_reads_is_reported_as_written(long_project):
    root, _ = long_project
    write_waves_as(root, {"1": "T1", "2": "T2", "3": "3"})
    path = root / "data" / "parent_long.csv"
    long = pd.read_csv(path, dtype=str, keep_default_na=False)
    long.loc[long.index[:1], "wave"] = "2"
    long.to_csv(path, index=False)
    (found,) = [i for i in run_catalog(root).report.issues if i.code == "wave_unclaimed"]
    assert found.details["waves"] == ["2"]


def test_repeating_a_wave_written_another_way_suggests_the_next_value(long_project):
    root, _ = long_project
    long = write_waves_as(root, {w: f"T{w}" for w in WAVES})
    fourth = long[long["wave"] == "T3"].assign(wave="T4")
    pd.concat([long, fourth]).to_csv(root / "data" / "parent_long.csv", index=False)
    project = load_project(root)
    draft = new_dataset.suggest(project, "parent_w3")
    assert (draft.name, draft.wave, draft.wave_value) == ("parent_w4", "4", "T4")
    # From a wave_unclaimed fix, the value is how the file writes the wave.
    seen = new_dataset.suggest(project, "parent_w3", "T4")
    assert (seen.wave, seen.wave_value) == ("4", "T4")
    placement = new_dataset.place(project, draft, None)
    dataset = new_dataset.dataset_config(project, draft, placement)
    assert new_dataset.wave_rows(project, dataset).rows == len(fourth)
    rows = new_dataset.template_rows(project, "parent_w3")
    changes.write(project, new_dataset.changes(project, draft, placement, rows))
    line = next(
        x
        for x in (root / "labcatalog.yaml").read_text(encoding="utf-8").splitlines()
        if "name: parent_w4" in x
    )
    assert "wave_column: wave, wave_value: T4," in line
    assert len(load_datasets(load_project(root))["parent_w4"].frame) == len(fourth)
