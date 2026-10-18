import re
import shutil

import pandas as pd
import pytest

from labcatalog.metadata import changes, fixes, new_dataset, studies
from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project
from labcatalog.sources import load_datasets

WAVES = ("1", "2", "3")


def share_one_map(root):
    # The three parent files as one long file in the same columns, read through maps/parent.csv.
    frames = []
    for w in WAVES:
        frame = pd.read_csv(root / "data" / f"parent_w{w}.csv", dtype=str, keep_default_na=False)
        frames.append(frame.rename(columns=lambda c, w=w: re.sub(rf"_w{w}$", "", c)).assign(wave=w))
    long = pd.concat(frames, ignore_index=True).fillna("")
    long.to_csv(root / "data" / "parent_long.csv", index=False)
    rows = pd.read_csv(root / "maps" / "parent_w1.csv", dtype=str, keep_default_na=False)
    rows["column"] = rows["column"].str.replace(r"_w1$", "", regex=True)
    rows = pd.concat([rows, pd.DataFrame([{"column": "wave", "instrument": "", "item": ""}])])
    rows.to_csv(root / "maps" / "parent.csv", index=False, lineterminator="\n")
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    for w in WAVES:
        (root / "maps" / f"parent_w{w}.csv").unlink()
        old = f"path: data/parent_w{w}.csv,"
        assert old in text
        text = text.replace(old, "path: data/parent_long.csv, wave_column: wave, map: parent,")
    config.write_text(text, encoding="utf-8")


@pytest.fixture
def shared(mock_project, tmp_path):
    wide = tmp_path / "wide"
    shutil.copytree(mock_project, wide)
    share_one_map(mock_project)
    return mock_project, wide


def test_datasets_that_share_a_map_score_as_with_their_own(shared):
    root, wide = shared
    found, before = run_catalog(root), run_catalog(wide)
    for w in WAVES:
        name = f"parent_w{w}"
        mine = found.scores[name].assign(pid=found.datasets[name].frame["pid"])
        theirs = before.scores[name].assign(pid=before.datasets[name].frame["pid"])
        pd.testing.assert_frame_equal(
            mine.sort_values([*mine.columns]).reset_index(drop=True),
            theirs.sort_values([*theirs.columns]).reset_index(drop=True),
        )
    assert {i.code for i in found.report.issues} == {i.code for i in before.report.issues}
    assert not [i for i in validate_project(load_project(root)) if "parent" in i.location]


def test_a_map_no_dataset_reads_is_still_reported(shared):
    root, _ = shared
    (root / "maps" / "parent_w9.csv").write_text("column,instrument,item\npid,,\n")
    (issue,) = [i for i in validate_project(load_project(root)) if "parent_w9" in i.location]
    assert issue.message == "no dataset named 'parent_w9' in labcatalog.yaml"


def test_a_row_twice_in_a_shared_map_is_reported_once(shared):
    root, _ = shared
    with open(root / "maps" / "parent.csv", "a", encoding="utf-8") as f:
        f.write("eps_1,example_parent_stress,eps_1\n")
    found = [i for i in validate_project(load_project(root)) if i.code == "duplicate_id"]
    assert [i.location.split(":")[0] for i in found] == ["maps/parent.csv"]


def test_a_fix_for_one_dataset_changes_the_shared_map(shared):
    root, _ = shared
    project = load_project(root)
    assert fixes.map_file(project, "parent_w2") == "maps/parent.csv"
    found = fixes.map_rows(project, "parent_w2", [("notes", "", "")])
    assert found.path == "maps/parent.csv"
    changes.write(project, [found])
    assert (root / "maps" / "parent.csv").read_text(encoding="utf-8").endswith("notes,,\n")


def test_the_next_wave_of_a_shared_long_file_shares_its_map(shared):
    root, _ = shared
    path = root / "data" / "parent_long.csv"
    long = pd.read_csv(path, dtype=str, keep_default_na=False)
    pd.concat([long, long[long["wave"] == "3"].assign(wave="4")]).to_csv(path, index=False)
    project = load_project(root)
    draft = new_dataset.suggest(project, "parent_w3")
    placement = new_dataset.place(project, draft, None)
    rows = new_dataset.template_rows(project, "parent_w3")
    found = new_dataset.changes(project, draft, placement, rows)
    assert "maps/parent_w4.csv" not in [c.path for c in found]
    changes.write(project, found)
    after = load_project(root)
    assert next(d for d in after.config.datasets if d.name == "parent_w4").map == "parent"
    assert not [i for i in validate_project(after) if "parent_w4" in i.message]
    assert len(load_datasets(after)["parent_w4"].frame) == (long["wave"] == "3").sum()


def test_a_shared_map_stays_while_another_study_reads_it(shared):
    root, _ = shared
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if "name: parent_w3," in x)
    copied = line.replace("name: parent_w3", "name: pilot_parent_w1").replace(
        "study: mock_study", "study: pilot"
    )
    config.write_text(text.replace(line, f"{line}\n{copied}"), encoding="utf-8")
    changes.write(load_project(root), studies.new_study(load_project(root), "pilot", "Pilot"))
    removed = studies.delete_study(load_project(root), "pilot")
    assert "labcatalog.yaml" in [c.path for c in removed]
    assert "maps/parent.csv" not in [c.path for c in removed if c.removed]


def test_rows_of_an_instrument_not_given_name_the_dataset(mock_project):
    with open(mock_project / "maps" / "parent_w1.csv", "a", encoding="utf-8") as f:
        f.write("ems_1_w1,example_mood,ems_1\n")
    found = validate_project(load_project(mock_project))
    (stray,) = [i for i in found if "not administered" in i.message]
    assert stray.message == "instrument 'example_mood' is not administered in parent_w1 (1 rows)"
    # The dataset's own checks after it still name the dataset.
    assert all(i.details["dataset"] != "example_mood" for i in found if i.code == "unmapped_item")
