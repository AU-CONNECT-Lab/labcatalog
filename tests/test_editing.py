import os

import pytest

from labcatalog import editing
from labcatalog.exceptions import EditError
from labcatalog.project import load_project

MOOD = "instruments/example_mood.yaml"


def test_files_are_listed_by_kind(mock_project):
    files = editing.editable_files(mock_project)
    assert files["Settings"] == ["labcatalog.yaml"]
    assert MOOD in files["Instruments"]
    assert files["Studies"] == ["studies/mock_study.yaml"]
    assert "maps/child_w1.csv" in files["Column maps"]


def test_checks_find_syntax_and_field_problems(mock_project):
    text = editing.open_file(mock_project, MOOD).text
    assert editing.check_text(MOOD, text) == []
    [broken] = editing.check_text(MOOD, text.replace("name: Example", "name: [Example"))
    assert broken.code == "yaml_syntax" and broken.location.startswith(MOOD + ":")
    unknown = editing.check_text(MOOD, text + "colour: blue\n")
    assert any("colour" in i.message for i in unknown)
    assert editing.check_text("labcatalog.yaml", "project: {}\n")
    assert editing.check_text("maps/child_w1.csv", "nothing,here\n")


def test_saving_keeps_line_endings_and_refuses_a_file_changed_meanwhile(mock_project):
    path = mock_project / MOOD
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    opened = editing.open_file(mock_project, MOOD)
    assert "\r" not in opened.text
    saved = editing.save_file(mock_project, opened, opened.text.replace("EMS", "EMS2", 1))
    assert b"abbreviation: EMS2\r\n" in path.read_bytes()
    stamp = saved.modified + 5_000_000_000
    os.utime(path, ns=(stamp, stamp))
    with pytest.raises(EditError, match="changed on disk"):
        editing.save_file(mock_project, saved, saved.text)


def test_new_instrument_is_a_valid_file(mock_project):
    path = editing.new_instrument(mock_project, "new_scale")
    assert path == "instruments/new_scale.yaml"
    assert load_project(mock_project).instruments["new_scale"].name == "New scale"
    with pytest.raises(EditError, match="already exists"):
        editing.new_instrument(mock_project, "new_scale")
    with pytest.raises(EditError, match="lower-case"):
        editing.new_instrument(mock_project, "New Scale")
