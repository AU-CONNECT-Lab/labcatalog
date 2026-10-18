import sys

import pandas as pd
import pytest

from labcatalog.cli import main
from labcatalog.metadata.browse import build_index, matches
from labcatalog.pipeline import run_catalog
from labcatalog.reports.export import (
    BY_DATASET,
    BY_GROUP,
    BY_ID,
    COLUMNS,
    ITEM_STATISTICS,
    SCORE_STATISTICS,
    VARIABLES,
    data_frame,
    export_plan,
    layouts,
    variable_rows,
    write_export,
)
from labcatalog.stats.cfa import CfaFit


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
    assert list(frame.columns[:4]) == ["pid", "family", "visit_date", "eps_1_w1"]
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


def test_export_writes_a_new_folder_in_outputs(result):
    plan = {"child_w1": ["example_mood"], "child_w2": ["example_mood"]}
    done = write_export(result, plan, BY_DATASET)
    folder = done.folder
    assert folder.parent == result.project.root / "outputs" and folder.name.endswith("_export")
    assert sorted(p.name for p in folder.iterdir()) == [
        "child_w1.csv",
        "child_w2.csv",
        ITEM_STATISTICS,
        "manifest.json",
        SCORE_STATISTICS,
        VARIABLES,
    ]
    assert done.left_out == {}
    assert (folder / VARIABLES).read_bytes().startswith(b"\xef\xbb\xbf")
    data = pd.read_csv(folder / "child_w2.csv", dtype=str, keep_default_na=False)
    assert len(data) == len(result.datasets["child_w2"].frame)
    assert not (folder / "child_w2.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_wide_table_by_id_has_a_row_per_person_and_leaves_out_repeated_ids(result):
    plan = {"parent_w2": ["example_parent_stress"], "parent_w3": ["example_parent_stress"]}
    done = write_export(result, plan, BY_ID)
    data = pd.read_csv(done.folder / "data_by_id.csv", dtype=str, keep_default_na=False)
    variables = pd.read_csv(done.folder / VARIABLES, dtype=str, keep_default_na=False)
    assert done.left_out == {"parent_w3": 2}
    assert data.columns[0] == "id" and data["id"].is_unique
    assert {"parent_w2_eps_1_w2", "parent_w3_eps_1_w3", "parent_w3_visit_date"} <= set(data)
    assert "parent_w2_pid" not in data
    assert set(variables["column"]) <= set(data)
    by_id = data.set_index("id")
    assert by_id.loc["1005P", "parent_w3_eps_1_w3"] == ""
    raw = result.datasets["parent_w2"].frame.set_index("pid")["eps_1_w2"].astype(str)
    person = raw.index[0]
    assert by_id.loc[person, "parent_w2_eps_1_w2"] == raw[person]


def test_wide_table_by_group_puts_parent_and_child_side_by_side(result):
    plan = {"parent_w1": ["example_parent_stress"], "child_w1": ["example_mood"]}
    assert layouts(result, plan) == [BY_DATASET, BY_ID, BY_GROUP]
    done = write_export(result, plan, BY_GROUP)
    data = pd.read_csv(done.folder / "data_by_family.csv", dtype=str, keep_default_na=False)
    assert data.columns[0] == "family" and data["family"].is_unique
    row = data.set_index("family").loc["1001"]
    assert (row["parent_w1_pid"], row["child_w1_pid"]) == ("1001P", "1001C")


def run_cli(monkeypatch, capsys, *args: str) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["labcatalog", "export", *args])
    with pytest.raises(SystemExit) as caught:
        main()
    out = capsys.readouterr()
    return caught.value.code, out.out, out.err


def test_cli_exports_named_instruments(mock_project, monkeypatch, capsys):
    p = ["-p", str(mock_project)]
    code, out, _ = run_cli(monkeypatch, capsys, "example_mood", "-d", "child_w3", *p)
    assert code == 0
    folder = next((mock_project / "outputs").iterdir())
    assert out.strip() == f"Wrote {folder.resolve()}"
    assert sorted(f.name for f in folder.iterdir()) == [
        "child_w3.csv",
        ITEM_STATISTICS,
        "manifest.json",
        SCORE_STATISTICS,
        VARIABLES,
    ]
    code, out, _ = run_cli(monkeypatch, capsys, "example_parent_stress", "--by", "id", *p)
    assert code == 0 and "Left out 2 rows of parent_w3: their id repeats in that file" in out
    code, _, err = run_cli(monkeypatch, capsys, "example_mood", "--by", "row", *p)
    assert (code, err.strip()) == (
        1,
        "Error: Cannot export by row; these datasets allow dataset, id, group",
    )
    code, _, err = run_cli(monkeypatch, capsys, "example_mood", "nope", *p)
    assert (code, err.strip()) == (1, "Error: Not an instrument or dataset in this project: nope")
    code, _, err = run_cli(monkeypatch, capsys, "example_mood", "-d", "parent_w1", *p)
    assert (code, err.strip()) == (1, "Error: None of these instruments is in these datasets")


def test_statistics_match_the_summary_and_leave_out_open_answers(result):
    plan = {"child_w1": ["example_mood"], "parent_w1": ["example_demographics"]}
    done = write_export(result, plan, BY_DATASET)
    scores = pd.read_csv(done.folder / SCORE_STATISTICS, encoding="utf-8-sig")
    total = scores.set_index("score").loc["ems_total"]
    key = next(s.key for s in result.catalog.scores_for("child_w1") if s.score_id == "ems_total")
    summary = next(s for s in result.summary.scores if s.key == key)
    assert (total["n"], total["alpha"]) == (summary.n_valid, pytest.approx(summary.alpha))
    assert (total["possible_min"], total["possible_max"]) == (0, 27)
    items = pd.read_csv(done.folder / ITEM_STATISTICS, encoding="utf-8-sig", keep_default_na=False)
    assert "dem_comment_w1" not in set(items["column"])
    gender = items.set_index("column").loc["dem_gender_w1"]
    assert gender["counts"] == "1=90; 2=96; 3=2" and gender["missing"] == "blank=2; refused=1"
    wide = write_export(result, {"child_w1": ["example_mood"]}, BY_ID)
    columns = pd.read_csv(wide.folder / SCORE_STATISTICS, encoding="utf-8-sig")["column"]
    assert all(c.startswith("child_w1_") for c in columns)


def test_score_statistics_carry_the_omega_of_the_window_s_factor_models(result):
    plan = {"child_w1": ["example_mood"]}
    fit = CfaFit("example_mood", "child_w1", "one factor", {}, 180, omega={"ems_total": 0.87})
    scores = pd.read_csv(
        write_export(result, plan, BY_DATASET, [fit]).folder / SCORE_STATISTICS,
        encoding="utf-8-sig",
    ).set_index("score")
    assert scores.loc["ems_total", "omega"] == pytest.approx(0.87)
    assert scores.drop("ems_total")["omega"].isna().all()
