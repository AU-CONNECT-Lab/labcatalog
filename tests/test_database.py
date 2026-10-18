import duckdb
import pandas as pd
from typer.testing import CliRunner

from labcatalog.cli import app
from labcatalog.pipeline import run_catalog, run_freeze
from labcatalog.reports.database import run_database
from labcatalog.reports.export import variable_rows


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


def test_the_command_builds_the_database(mock_project):
    done = CliRunner().invoke(app, ["database", "-p", str(mock_project)])
    assert done.exit_code == 0 and "labcatalog.duckdb" in done.output


def test_a_freeze_keeps_its_own_copy_of_the_database(mock_project):
    path, _ = run_freeze(mock_project, "pilot", None)
    copy = path.with_suffix(".duckdb")
    with duckdb.connect(str(copy), read_only=True) as con:
        assert con.execute('SELECT count(*) FROM data."child_w1"').fetchone()[0] > 0
