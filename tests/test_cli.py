import sys

import pytest
from typer.testing import CliRunner

from labcatalog.cli import app, main

runner = CliRunner()


def test_validate_clean_project(demo_project):
    result = runner.invoke(app, ["validate", "-p", str(demo_project)])
    assert result.exit_code == 0
    assert "No problems found." in result.output


def test_validate_reports_problems_with_exit_code_1(demo_project):
    config = demo_project / "labcatalog.yaml"
    config.write_text(config.read_text().replace("project:", "projct:"))
    result = runner.invoke(app, ["validate", "-p", str(demo_project)])
    assert result.exit_code == 1
    assert "labcatalog.yaml: error [extra_forbidden] projct:" in result.output
    assert "2 error(s), 0 warning(s)" in result.output


def test_missing_project_exits_with_code_3(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["labcatalog", "validate", "-p", str(tmp_path)])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 3
    assert "No labcatalog.yaml found" in capsys.readouterr().err
