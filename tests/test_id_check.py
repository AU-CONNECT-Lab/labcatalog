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
