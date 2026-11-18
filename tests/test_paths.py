import sys
from pathlib import Path

import pytest

from labcatalog.paths import clean_file_url, expand_path


def test_relative_paths_resolve_against_the_config_folder(tmp_path):
    assert expand_path("data/a.csv", tmp_path) == tmp_path / "data" / "a.csv"


def test_environment_variables_and_home_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("LAB_DATA", str(tmp_path))
    assert expand_path("$LAB_DATA/a.csv", Path("elsewhere")) == tmp_path / "a.csv"
    assert expand_path("~/a.csv", tmp_path) == Path.home() / "a.csv"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows writes variables as %NAME%")
def test_windows_variables_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    assert expand_path("%DATA_ROOT%/a.csv", Path("elsewhere")) == tmp_path / "a.csv"


def test_a_percent_sign_is_kept_outside_a_file_url(tmp_path):
    assert expand_path("data/50%25.csv", tmp_path) == tmp_path / "data" / "50%25.csv"


def test_windows_backslashes_are_accepted(tmp_path):
    assert expand_path(r"data\a.csv", tmp_path) == tmp_path / "data" / "a.csv"


def test_file_urls_are_cleaned():
    assert clean_file_url("file:///C:/Box/My%20Lab/a.pdf") == "C:/Box/My Lab/a.pdf"
