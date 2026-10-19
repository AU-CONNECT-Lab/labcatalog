import sys

import pytest
from typer.testing import CliRunner

from labcatalog import gui
from labcatalog.cli import app, main
from labcatalog.exceptions import ProjectNotFoundError
from labcatalog.project import init_project

runner = CliRunner()


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
