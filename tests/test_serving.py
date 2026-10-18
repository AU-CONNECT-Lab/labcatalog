import shutil

import pytest
from typer.testing import CliRunner

from labcatalog import defaults
from labcatalog.cli import app
from labcatalog.gui import common, files, preferences, serving
from labcatalog.metadata import accepted
from labcatalog.project import find_projects


@pytest.fixture(autouse=True)
def settings_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(preferences, "folder", lambda: tmp_path / "settings")


@pytest.fixture
def served(tmp_path, monkeypatch):
    folder = tmp_path / "projects"
    for name in ("alpha", "lab/beta"):
        (folder / name).mkdir(parents=True)
        (folder / name / defaults.CONFIG_FILENAME).write_text("project: {name: x}\n")
    (folder / "alpha" / "inside").mkdir()
    (folder / "alpha" / "inside" / defaults.CONFIG_FILENAME).write_text("project: {name: y}\n")
    (folder / "notes").mkdir()
    monkeypatch.setattr(common, "serving", folder.resolve())
    return folder


def test_each_browser_keeps_its_own_settings_and_the_computer_keeps_its_paths(monkeypatch):
    preferences.save({preferences.RSCRIPT: "Rscript", preferences.PALETTE: "lancet"})
    browser = {}
    monkeypatch.setattr(preferences, "browser", lambda: browser)
    preferences.save_mine({preferences.PALETTE: "nature", preferences.WHO: "Ana"})
    assert preferences.mine() == {preferences.PALETTE: "nature", preferences.WHO: "Ana"}
    assert preferences.load()[preferences.PALETTE] == "lancet"
    assert preferences.load()[preferences.RSCRIPT] == "Rscript"


def test_the_secret_outlasts_a_restart():
    assert preferences.server_secret() == preferences.server_secret()


def test_the_project_list_finds_projects_but_not_inside_one(served):
    assert find_projects(served) == [served / "alpha", served / "lab" / "beta"]


def test_the_chooser_and_the_last_project_stay_inside_the_folder(served, tmp_path, monkeypatch):
    assert files.allowed(served / "lab" / "beta")
    assert not files.allowed(tmp_path)
    browser = {preferences.LAST_PROJECT: str(tmp_path)}
    monkeypatch.setattr(preferences, "browser", lambda: browser)
    assert serving.start_folder() is None
    browser[preferences.LAST_PROJECT] = str(served / "alpha")
    assert serving.start_folder() == served / "alpha"
    shutil.rmtree(served / "alpha")
    assert serving.start_folder() is None


def test_what_someone_changes_carries_the_name_they_gave(tmp_path, monkeypatch):
    monkeypatch.setattr(accepted, "named", lambda: "Ana")
    assert accepted.who(tmp_path) == "Ana"
    monkeypatch.setattr(accepted, "named", accepted.nobody)
    assert accepted.who(tmp_path) != "Ana"


def test_serve_needs_a_folder(tmp_path):
    found = CliRunner().invoke(app, ["serve", str(tmp_path / "missing")])
    assert found.exit_code != 0 and "is not a folder" in found.output
