from pathlib import Path

import pytest

from labcatalog import defaults
from labcatalog.gui import example, preferences


@pytest.fixture(autouse=True)
def settings_folder(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(preferences, "folder", lambda: tmp_path / "settings")
    return tmp_path / "settings"


def test_the_first_start_opens_a_copy_of_the_example(settings_folder):
    folder = example.start_folder()
    assert folder == settings_folder / "example"
    assert (folder / defaults.CONFIG_FILENAME).is_file()
    assert (folder / defaults.SCHEMAS_DIR).is_dir()


def test_later_starts_open_the_last_project_while_it_exists(tmp_path):
    project = tmp_path / "mine"
    project.mkdir()
    (project / defaults.CONFIG_FILENAME).write_text("project: {name: Mine}\n")
    preferences.save({preferences.LAST_PROJECT: str(project)})
    assert example.start_folder() == project
    (project / defaults.CONFIG_FILENAME).unlink()
    assert example.start_folder() == example.example_folder()


def test_reset_puts_the_example_back_as_installed():
    config = example.example_copy() / defaults.CONFIG_FILENAME
    original = config.read_text(encoding="utf-8")
    config.write_text("changed\n", encoding="utf-8")
    assert example.example_copy() == config.parent
    assert config.read_text(encoding="utf-8") == "changed\n"
    example.reset_example()
    assert config.read_text(encoding="utf-8") == original
