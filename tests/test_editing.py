import os

import pytest

from labcatalog.config import FreedParameter
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing
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
    saved = editing.save_file(mock_project, saved, saved.text.rstrip("\n"))
    assert path.read_bytes().endswith(b"emotion\r\n")
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


def test_a_draft_is_listed_checked_and_moved_into_instruments(mock_project):
    drafts = mock_project / "drafts"
    drafts.mkdir()
    text = (mock_project / MOOD).read_text(encoding="utf-8").replace("example_mood", "mood_two")
    (drafts / "mood_two.yaml").write_text(text, encoding="utf-8")
    assert editing.editable_files(mock_project)["Drafts"] == ["drafts/mood_two.yaml"]
    assert editing.check_text("drafts/mood_two.yaml", text + "colour: blue\n")
    assert "mood_two" not in load_project(mock_project).instruments
    assert editing.move_draft(mock_project, "drafts/mood_two.yaml") == "instruments/mood_two.yaml"
    assert "mood_two" in load_project(mock_project).instruments
    (drafts / "mood_two.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(EditError, match="already exists"):
        editing.move_draft(mock_project, "drafts/mood_two.yaml")


def test_freed_parameters_are_saved_into_the_stats_settings(mock_project):
    freed = [FreedParameter(instrument="example_mood", item="ems_2", parameter="loading")]
    editing.save_freed(mock_project, freed)
    text = (mock_project / "labcatalog.yaml").read_text()
    assert "correlate_by: family" in text and "# Score correlations link" in text
    assert load_project(mock_project).config.stats.invariance_free == freed
    editing.save_freed(mock_project, [])
    assert "invariance_free" not in (mock_project / "labcatalog.yaml").read_text()


def test_lab_settings_are_saved_into_the_project_without_their_defaults(mock_project):
    changes = {
        "stats": {"decimals": 3, "t_test": "student", "correlation": "pearson"},
        "llm": {"provider": "local", "model": "qwen3"},
    }
    editing.save_settings(mock_project, changes)
    text = (mock_project / "labcatalog.yaml").read_text()
    assert "correlate_by: family" in text and "# Score correlations link" in text
    assert "correlation:" not in text
    config = load_project(mock_project).config
    assert (config.stats.decimals, config.stats.t_test) == (3, "student")
    assert (config.llm.provider, config.llm.model) == ("local", "qwen3")
    editing.save_settings(mock_project, {"llm": {"provider": "anthropic", "model": None}})
    assert "llm:" not in (mock_project / "labcatalog.yaml").read_text()
