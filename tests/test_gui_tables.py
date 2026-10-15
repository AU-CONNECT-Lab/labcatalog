from pathlib import Path

from labcatalog.browse import build_index, matches
from labcatalog.gui import datasets, instruments, overview
from labcatalog.gui.common import location_path
from labcatalog.pipeline import run_catalog


def test_location_path_drops_the_line_number():
    root = Path("project")
    assert location_path(root, "studies/demo_study.yaml:5") == root / "studies/demo_study.yaml"
    outside = Path.cwd() / "data" / "parent_w1.csv"
    assert location_path(root, f"{outside.as_posix()}:3") == outside


def test_wave_table(mock_project):
    result = run_catalog(mock_project)
    _, waves = overview.wave_table(result)
    assert [(w["wave"], w["n_parent"], w["n_child"]) for w in waves] == [
        ("1", 116, 111),
        ("2", 38, 34),
    ]


def test_instrument_list_shows_only_the_matched_datasets(mock_project):
    result = run_catalog(mock_project)
    index = build_index(result.project)
    found = matches(index, {"reporter": {"child"}})
    columns, rows = instruments.list_table(result, found)
    assert [c["label"] for c in columns[-2:]] == ["child_w1", "child_w2"]
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"example_mood", "example_screen_time"}
    assert (by_id["example_screen_time"]["d0"], by_id["example_screen_time"]["d1"]) == ("", 34)
    assert by_id["example_mood"]["reporters"] == "child"


def test_instrument_items_list_each_dataset_column(mock_project):
    result = run_catalog(mock_project)
    columns, rows = instruments.item_table(result, result.project.instruments["example_mood"])
    assert [c["label"] for c in columns[-2:]] == ["child_w1", "child_w2"]
    assert (rows[0]["d0"], rows[0]["d1"]) == ("ems_1_w1", "ems_1_w2")


def test_dataset_issues_cover_its_data_file_only(mock_project):
    result = run_catalog(mock_project)
    codes = [i.code for i in datasets.dataset_issues(result, "child_w1")]
    assert sorted(codes) == ["same_answer", "unexpected_value"]
