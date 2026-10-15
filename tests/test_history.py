import shutil
import subprocess

import pytest

from labcatalog.history import UNCOMMITTED, file_history
from labcatalog.project import init_project

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

MOOD = "instruments/example_mood.yaml"


def git(root, *args: str) -> None:
    identity = ["-c", "user.name=Ada", "-c", "user.email=ada@example.org"]
    subprocess.run(["git", "-C", str(root), *identity, *args], check=True, capture_output=True)


def note(path, text: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(f"# {text}\n")


def test_history_lists_commits_newest_first_under_uncommitted_changes(tmp_path):
    root = init_project(tmp_path / "lab")
    git(root, "init")
    git(root, "add", ".")
    git(root, "commit", "-m", "Start the catalog")
    note(root / MOOD, "Wording checked against the manual.")
    git(root, "commit", "-am", "Check wording")
    note(root / MOOD, "Still to check: item 4.")

    changes = file_history(root, MOOD)
    assert [c.message for c in changes] == [UNCOMMITTED, "Check wording", "Start the catalog"]
    assert changes[0].commit is None
    assert "+# Still to check: item 4." in changes[0].diff
    assert changes[1].author == "Ada"
    assert "+# Wording checked against the manual." in changes[1].diff
    assert "Still to check" not in changes[1].diff

    (root / "instruments" / "new.yaml").write_text("id: new\n", encoding="utf-8")
    [change] = file_history(root, "instruments/new.yaml")
    assert change.message == UNCOMMITTED
    assert change.diff == "This file is not in git yet."


def test_no_history_outside_git(tmp_path):
    root = init_project(tmp_path / "lab")
    assert file_history(root, MOOD) is None
