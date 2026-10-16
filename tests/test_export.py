import pandas as pd
import pytest

from labcatalog.browse import build_index, matches
from labcatalog.export import (
    COLUMNS,
    VARIABLES,
    data_frame,
    export_plan,
    variable_rows,
    write_export,
)
from labcatalog.pipeline import run_catalog


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def found_for(result, **selected: set[str]) -> dict[str, list[str]]:
    return matches(build_index(result.project), selected)


def test_plan_keeps_the_chosen_instruments_in_the_filtered_datasets(result):
    chosen = {"example_mood", "example_demographics"}
    assert export_plan(result, found_for(result), chosen) == {
        "parent_w1": ["example_demographics"],
        "parent_w2": ["example_demographics"],
        "parent_w3": ["example_demographics"],
        "child_w1": ["example_mood"],
        "child_w2": ["example_mood"],
        "child_w3": ["example_mood"],
    }
    assert export_plan(result, found_for(result, wave={"mock_study/2"}), chosen) == {
        "parent_w2": ["example_demographics"],
        "child_w2": ["example_mood"],
    }


def test_variable_list_has_items_then_scores(result):
    rows = variable_rows(result, {"child_w1": ["example_mood"]})
    assert all(list(row) == COLUMNS for row in rows)
    items = [r for r in rows if r["kind"] == "item"]
    scores = [r for r in rows if r["kind"] == "score"]
    assert [r["column"] for r in items] == [f"ems_{i}_w1" for i in range(1, 10)]
    first = items[0]
    assert (first["dataset"], first["wave"], first["reporter"], first["instrument"]) == (
        "child_w1",
        "1",
        "child",
        "example_mood",
    )
    assert first["options"].startswith("0=")
    assert "-99=refused" in first["missing_codes"]
    total = next(r for r in scores if r["item"] == "ems_total")
    assert total["column"] == "ems_total_child_w1"
    assert total["score_items"] == "; ".join(f"ems_{i}" for i in range(1, 10))
    assert all(r["in_data"] == "yes" for r in rows)


def test_data_keep_raw_values_add_scores_and_leave_out_open_answers(result):
    frame = data_frame(result, "parent_w1", ["example_demographics", "example_parent_stress"])
    raw = result.datasets["parent_w1"].frame
    assert list(frame.columns[:3]) == ["pid", "visit_date", "eps_1_w1"]
    assert frame["eps_1_w1"].equals(raw["eps_1_w1"])
    assert "dem_comment_w1" not in frame and "dem_age_w1" in frame
    score = "example_parent_stress.eps_mean@parent_w1"
    assert frame["eps_mean_parent_w1"].equals(result.scores["parent_w1"][score])
    comment = next(
        r
        for r in variable_rows(result, {"parent_w1": ["example_demographics"]})
        if r["column"] == "dem_comment_w1"
    )
    assert (comment["type"], comment["in_data"]) == ("text", "no")


def test_export_writes_a_new_folder(result, tmp_path):
    plan = {"child_w1": ["example_mood"], "child_w2": ["example_mood"]}
    folder = write_export(result, plan, tmp_path)
    assert folder.parent == tmp_path and folder.name.startswith("labcatalog_export_")
    assert sorted(p.name for p in folder.iterdir()) == ["child_w1.csv", "child_w2.csv", VARIABLES]
    assert (folder / VARIABLES).read_bytes().startswith(b"\xef\xbb\xbf")
    data = pd.read_csv(folder / "child_w2.csv", dtype=str, keep_default_na=False)
    assert len(data) == len(result.datasets["child_w2"].frame)
    assert not (folder / "child_w2.csv").read_bytes().startswith(b"\xef\xbb\xbf")
