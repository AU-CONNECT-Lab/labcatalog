import duckdb
import pandas as pd

from labcatalog.pipeline import run_catalog, run_freeze
from labcatalog.project import init_project
from labcatalog.reports.database import run_database
from labcatalog.reports.export import variable_rows
from tests.test_folder_source import add_scans


def test_the_database_holds_the_data_and_what_they_mean(mock_project):
    path = run_database(mock_project)
    assert path == mock_project / "database" / "labcatalog.duckdb"
    assert not list(path.parent.glob("*.partial"))
    result = run_catalog(mock_project)
    with duckdb.connect(str(path), read_only=True) as con:
        names = {row[0] for row in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
        assert {"child_w1", "parent_w1", "eeg_w1", "variables", "build", "files"} <= names
        child = con.execute('SELECT * FROM data."child_w1"').df()
        assert len(child) == len(result.datasets["child_w1"].frame)
        types = dict(
            con.execute(
                'SELECT column_name, column_type FROM (DESCRIBE data."child_w1")'
            ).fetchall()
        )
        assert (types["pid"], types["ems_1_w1"], types["visit_date"]) == (
            "VARCHAR",
            "DOUBLE",
            "DATE",
        )
        total = "example_mood.ems_total@child_w1"
        pd.testing.assert_series_equal(
            child.filter(like="ems_total").iloc[:, 0],
            result.scores["child_w1"][total].reset_index(drop=True),
            check_names=False,
        )
        parent = con.execute('SELECT * FROM data."parent_w1"').df()
        # Open answers can identify people, so they stay out as they do in exports.
        assert not any(c.startswith("dem_comment") for c in parent.columns)
        variables = con.execute("SELECT * FROM variables").df()
        plan = {name: [] for name in result.datasets}
        assert len(variables) > len(variable_rows(result, plan))
        assert con.execute("SELECT metadata_commit FROM build").fetchone()[0] == (
            result.manifest.metadata_commit
        )
    # Built again from scratch, not added to.
    run_database(mock_project)
    with duckdb.connect(str(path), read_only=True) as con:
        assert con.execute('SELECT count(*) FROM data."child_w1"').fetchone()[0] == len(child)


def test_a_freeze_keeps_its_own_copy_of_the_database(mock_project):
    path, _ = run_freeze(mock_project, "pilot", None)
    copy = path.with_suffix(".duckdb")
    with duckdb.connect(str(copy), read_only=True) as con:
        assert con.execute('SELECT count(*) FROM data."child_w1"').fetchone()[0] > 0


def test_a_project_without_datasets_still_gets_a_database(tmp_path):
    path = run_database(init_project(tmp_path / "blank", example=False))
    with duckdb.connect(str(path), read_only=True) as con:
        names = {row[0] for row in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    assert names == {"build"}


def test_each_file_of_a_folder_dataset_has_a_row_to_join_with_the_data(mock_project):
    add_scans(mock_project)
    (mock_project / "id_map.csv").write_text(
        "dataset,from,to\nscans_w1,1002C,9999C\n", encoding="utf-8"
    )
    path = run_database(mock_project)
    with duckdb.connect(str(path), read_only=True) as con:
        files = con.execute("SELECT * FROM folder_files").df()
        joined = con.execute(
            'SELECT f.path FROM folder_files f JOIN data."child_w1" c USING (pid)'
        ).fetchall()
    assert files.columns.tolist() == ["dataset", "study", "wave", "pid", "path", "size", "here"]
    func = "bids/sub-{0}/ses-1/func/sub-{0}_ses-1_task-rest{1}_bold.nii.gz"
    assert files[["dataset", "wave", "pid", "path"]].values.tolist() == [
        ["scans_w1", "1", "1001C", func.format("1001C", "_run-1")],
        ["scans_w1", "1", "1001C", func.format("1001C", "_run-2")],
        ["scans_w1", "1", "9999C", func.format("1002C", "")],
    ]
    assert files["size"].tolist() == [1, 1, 1] and files["here"].all()
    assert len(joined) == 2
