from pathlib import Path

import pandas as pd
import pytest

from labcatalog.exceptions import DataSourceError
from labcatalog.pipeline import run_catalog, run_check, run_validate
from labcatalog.project import load_project
from labcatalog.reports.export import data_frame
from labcatalog.sources import load_datasets


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def roster(root: Path) -> pd.DataFrame:
    return pd.read_csv(root / "data" / "participants.csv", dtype=str).set_index("pid")


def test_every_dataset_takes_its_groups_from_the_roster(mock_project):
    datasets = load_datasets(load_project(mock_project))
    families = roster(mock_project)["family_id"]
    # The EEG file holds only children's IDs; a second child's ID says nothing of the family.
    eeg = datasets["eeg_w1"]
    ids = eeg.frame[eeg.id_column]
    assert eeg.group.tolist() == families.loc[ids].tolist()
    child = datasets["child_w1"]
    second = child.frame[child.id_column] == "1301C"
    assert child.group[second].tolist() == [families.loc["1301C"]] != ["1301"]


def test_check_reports_ids_missing_from_the_roster_and_people_with_no_data(mock_project):
    issues = run_check(mock_project).issues
    [unlisted] = [i for i in issues if i.code == "id_not_in_roster"]
    assert (unlisted.location, unlisted.level) == ("data/child_w3.csv", "warning")
    assert "1341C" in unlisted.message
    [unused] = [i for i in issues if i.code == "roster_unused"]
    assert (unused.location, unused.level) == ("data/participants.csv", "info")
    # 1031P is in the data with a stray space, which check_ids reports on its own.
    assert "1211C, 1211P" in unused.message and "1031P" not in unused.message
    assert not any(i.code == "group_missing" for i in issues)


def test_check_reports_a_person_listed_twice_and_one_without_a_group(mock_project):
    path = mock_project / "data" / "participants.csv"
    text = path.read_text(encoding="utf-8")
    path.write_text(text + "1001C,1002,child,2016\n1211X,,child,2016\n", encoding="utf-8")
    issues = [i for i in run_check(mock_project).issues if i.location == "data/participants.csv"]
    codes = {i.code for i in issues}
    assert {"id_duplicate", "id_pattern", "group_missing"} <= codes
    datasets = load_datasets(load_project(mock_project))
    child = datasets["child_w1"]
    # A person listed twice belongs to no family until the roster is fixed.
    assert child.group[child.frame[child.id_column] == "1001C"].isna().all()


def test_a_missing_roster_column_is_named(mock_project):
    edit(mock_project / "labcatalog.yaml", "group_column: family_id", "group_column: household")
    with pytest.raises(DataSourceError, match="household"):
        load_datasets(load_project(mock_project))


def test_the_group_is_read_one_way_only(mock_project):
    yaml = mock_project / "labcatalog.yaml"
    edit(yaml, "    name: family\n", "    name: family\n    from_id: '^(\\d{4})'\n")
    [issue] = run_validate(mock_project)
    assert "one way only" in issue.message


def test_a_group_needs_from_id_or_a_roster_column(mock_project):
    edit(mock_project / "labcatalog.yaml", "  group_column: family_id\n", "")
    [issue] = run_validate(mock_project)
    assert issue.message.startswith("ids.group: needs from_id, or a roster")


def test_a_roster_group_column_needs_a_declared_group(mock_project):
    yaml = mock_project / "labcatalog.yaml"
    edit(yaml, "  group:\n    name: family\n", "")
    edit(yaml, "correlate_by: family", "correlate_by: id")
    [issue] = run_validate(mock_project)
    assert "declare ids.group" in issue.message


def test_exported_data_carry_the_group_from_the_roster(mock_project):
    result = run_catalog(mock_project)
    frame = data_frame(result, "eeg_w1", ["eeg_resting"])
    assert list(frame.columns[:2]) == ["pid", "family"]
    families = roster(mock_project)["family_id"]
    assert frame["family"].tolist() == families.loc[frame["pid"]].tolist()


def test_the_manifest_records_the_roster(mock_project):
    result = run_catalog(mock_project)
    [record] = [f for f in result.manifest.files if f.dataset == "roster"]
    assert (record.path, record.rows) == ("data/participants.csv", len(roster(mock_project)))
