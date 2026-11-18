import pandas as pd

from labcatalog.data import id_map
from labcatalog.gui import id_check, setup
from labcatalog.pipeline import run_catalog


def test_each_data_file_shows_its_id_problems_and_corrections(mock_project):
    result = run_catalog(mock_project)
    rows = {row.dataset: row for row in id_check.id_rows(result)}
    assert set(rows) == set(result.datasets)
    assert rows["parent_w1"].problems == {"id_whitespace": 1}
    assert rows["child_w3"].problems.get("id_not_in_roster", 0) >= 1
    assert rows["child_w1"].rows == len(result.datasets["child_w1"].frame)
    waiting = id_check.waiting(result)
    assert waiting == sum(bool(r.problems) for r in rows.values())
    assert setup.to_do(result)[setup.IDS] == f"{waiting} to check"
    pd.DataFrame({"dataset": ["parent_w1"], "from": [" 1031P"], "to": ["1031P"]}).to_csv(
        id_map.path_of(mock_project), index=False
    )
    fixed = {row.dataset: row for row in id_check.id_rows(run_catalog(mock_project))}
    assert fixed["parent_w1"].problems == {} and fixed["parent_w1"].corrected == 1


def test_a_map_with_another_header_corrects_no_file(mock_project):
    id_map.path_of(mock_project).write_text(
        "Dataset,From,To\nparent_w1, 1031P,1031P\n", encoding="utf-8"
    )
    rows = {row.dataset: row for row in id_check.id_rows(run_catalog(mock_project))}
    assert rows["parent_w1"].problems == {"id_whitespace": 1}
    assert all(row.corrected == 0 for row in rows.values())


def test_rows_without_an_id_are_no_id(mock_project):
    path = mock_project / "data" / "child_w1.csv"
    data = pd.read_csv(path, dtype=str, keep_default_na=False)
    data.loc[[0, 1], "pid"] = ["", "  "]
    data.to_csv(path, index=False)
    result = run_catalog(mock_project)
    rows = {row.dataset: row for row in id_check.id_rows(result)}
    ids = result.datasets["child_w1"].frame["pid"]
    assert rows["child_w1"].ids == ids[ids.str.strip() != ""].nunique() == ids.nunique() - 2


def test_each_problem_lists_the_ids_as_the_file_writes_them(mock_project):
    rows = {row.dataset: row for row in id_check.id_rows(run_catalog(mock_project))}
    assert rows["parent_w1"].shown == {"id_whitespace": ["' 1031P'"]}
    assert "1341C" in rows["child_w3"].shown["id_not_in_roster"]
