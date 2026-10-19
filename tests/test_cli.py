import json
import sys

import pytest
from typer.testing import CliRunner

from labcatalog import gui
from labcatalog.cli import app, main
from labcatalog.exceptions import ProjectNotFoundError
from labcatalog.gui import preferences
from labcatalog.project import init_project

runner = CliRunner()

PYTHON = json.dumps(f'"{sys.executable}"')[1:-1]
STEPS = f"""
prepare:
  - name: tally
    run: "{PYTHON} tally.py"
    inputs: [raw.txt]
    outputs: [tally.txt]
"""
TALLY = """\
from pathlib import Path
lines = Path("raw.txt").read_text().splitlines()
Path("tally.txt").write_text(str(len(lines)))
print(f"{len(lines)} lines")
"""


@pytest.fixture
def stepped(tmp_path, monkeypatch):
    monkeypatch.setattr(preferences, "folder", lambda: tmp_path / "settings")
    root = init_project(tmp_path / "lab", example=False)
    with (root / "labcatalog.yaml").open("a", encoding="utf-8") as file:
        file.write(STEPS)
    (root / "raw.txt").write_text("a\nb\n", encoding="utf-8")
    (root / "tally.py").write_text(TALLY, encoding="utf-8")
    return root


def test_check_a_clean_project(tmp_path):
    root = init_project(tmp_path / "blank", example=False)
    result = runner.invoke(app, ["check", "-p", str(root)])
    assert result.exit_code == 0
    assert "No problems found." in result.output


def test_check_reports_problems_with_exit_code_1(demo_project):
    config = demo_project / "labcatalog.yaml"
    config.write_text(config.read_text().replace("project:", "projct:"))
    result = runner.invoke(app, ["check", "-p", str(demo_project)])
    assert result.exit_code == 1
    assert "labcatalog.yaml: error [extra_forbidden] projct:" in result.output


def test_missing_project_exits_with_code_3(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["labcatalog", "check", "-p", str(tmp_path)])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 3
    assert "No labcatalog.yaml found" in capsys.readouterr().err


def test_with_no_command_the_window_opens(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(gui, "launch", lambda *args, **kwargs: opened.append(args))
    assert runner.invoke(app, ["-p", str(tmp_path), "--browser"]).exit_code == 0
    assert opened == [(tmp_path, True, None)]
    checked = runner.invoke(app, ["check", "-p", str(tmp_path)])
    assert isinstance(checked.exception, ProjectNotFoundError)
    assert len(opened) == 1


def test_run_takes_the_outdated_steps_then_checks_and_builds_the_database(stepped):
    result = runner.invoke(app, ["run", "-p", str(stepped)])
    assert result.exit_code == 0, result.output
    assert "== tally" in result.output and "2 lines" in result.output
    assert (stepped / "tally.txt").read_text(encoding="utf-8") == "2"
    assert (stepped / "database" / "labcatalog.duckdb").is_file()
    assert "No problems found." in result.output
    again = runner.invoke(app, ["run", "-p", str(stepped)])
    assert again.exit_code == 0
    assert "Every step is up to date." in again.output


def test_run_stops_at_a_failing_step_with_exit_code_1(stepped):
    (stepped / "tally.py").write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
    result = runner.invoke(app, ["run", "-p", str(stepped)])
    assert result.exit_code == 1
    assert "Step tally failed (exit code 3), so labcatalog stopped there." in result.output
    assert not (stepped / "database").exists()
