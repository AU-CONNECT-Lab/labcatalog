import json
import sys

import pytest

from labcatalog.cli import main
from labcatalog.pipeline import run_catalog, run_check, run_schema, run_validate
from labcatalog.project import init_project

MODELINE = "# yaml-language-server: $schema="


def test_example_project_is_copied_with_its_schemas(tmp_path):
    root = init_project(tmp_path / "new")
    errors = {i.code for i in run_check(root).issues if i.level == "error"}
    assert errors == {"unexpected_value", "id_whitespace"}
    for path in root.rglob("*.yaml"):
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith(MODELINE), path
        assert (path.parent / first.removeprefix(MODELINE)).is_file(), path


def test_blank_project_is_valid_and_empty(tmp_path):
    root = init_project(tmp_path / "#2 lab pilot", example=False)
    assert run_validate(root) == []
    result = run_catalog(root)
    assert result.project.config.project.name == "#2 lab pilot"
    assert result.summary.datasets == []
    assert (root / "schemas" / "labcatalog.schema.json").is_file()


def test_init_refuses_a_folder_that_has_files(tmp_path, monkeypatch, capsys):
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["labcatalog", "init", str(tmp_path)])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 3
    assert "is not empty" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == ["notes.txt"]


def test_schemas_accept_numbers_as_text_and_reject_unknown_keys(tmp_path):
    paths = {p.name: p for p in run_schema(tmp_path)}
    assert set(paths) == {
        "labcatalog.schema.json",
        "instrument.schema.json",
        "study.schema.json",
    }
    config = json.loads(paths["labcatalog.schema.json"].read_text(encoding="utf-8"))
    dataset = config["$defs"]["DatasetConfig"]
    assert dataset["properties"]["wave"]["type"] == ["string", "number"]
    assert dataset["additionalProperties"] is False
    instrument = json.loads(paths["instrument.schema.json"].read_text(encoding="utf-8"))
    assert instrument["additionalProperties"] is False
