import subprocess

from labcatalog.datalad.history import history
from labcatalog.datalad.sync import DatasetState, size_text, state_text, summary
from labcatalog.pipeline import run_data_status
from tests.test_datalad import (
    git,
    make_dataset,
    needs_git,
)


@needs_git
def test_the_status_counts_unsaved_changes_and_versions_not_pushed(mock_project, tmp_path):
    make_dataset(mock_project)
    root = mock_project.resolve()
    [state] = run_data_status(mock_project)
    assert (state.root, state.changed, state.sibling, state.ahead) == (root, [], None, None)
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "store.git")], check=True)
    git(mock_project, "remote", "add", "store", (tmp_path / "store.git").as_posix())
    [state] = run_data_status(mock_project)
    assert (state.sibling, state.ahead) == ("store", None)
    git(mock_project, "push", "-q", "store", "main")
    (mock_project / "notes.txt").write_text("checked\n", encoding="utf-8")
    [state] = run_data_status(mock_project)
    assert (state.changed, state.ahead, state.behind) == (["notes.txt"], 0, 0)
    git(mock_project, "add", "notes.txt")
    git(mock_project, "commit", "-q", "-m", "Notes")
    [state] = run_data_status(mock_project)
    assert (state.changed, state.ahead) == ([], 1)
    assert state_text(state) == "1 saved version(s) not pushed to store"


def test_the_status_reads_as_a_sentence(tmp_path):
    assert state_text(DatasetState(tmp_path, [], "store", 0, 0)) == "saved, and the same as store"
    assert state_text(DatasetState(tmp_path, ["a", "b"], None, None, None)) == (
        "2 unsaved change(s); no single sibling to push to"
    )
    assert state_text(DatasetState(tmp_path, [], "origin", 0, 3)) == "3 new version(s) on origin"


def test_the_header_names_what_needs_doing_first(tmp_path):
    def state(changed=(), ahead=0, behind=0, sibling="store"):
        return DatasetState(tmp_path, list(changed), sibling, ahead, behind)

    assert summary([state(["a"], ahead=2), state(behind=1)]) == ("1 unsaved", "warn")
    assert summary([state(ahead=2), state(behind=1)]) == ("2 to push", "warn")
    assert summary([state(behind=3)]) == ("3 to update", "info")
    assert summary([state(ahead=None)]) == ("Not pushed yet", "warn")
    assert summary([state(), state(sibling=None, ahead=None)]) == ("Data saved", "ok")


def test_the_status_says_how_much_is_here(tmp_path):
    state = DatasetState(tmp_path, [], "store", 0, 0, present=2_500_000, total=10_000_000_000)
    assert state_text(state) == "saved, and the same as store; 2.5 MB of 10.0 GB here"
    assert [size_text(n) for n in (0, 999, 1000, 4_200_000_000_000)] == [
        "0 bytes",
        "999 bytes",
        "1.0 KB",
        "4200.0 GB",
    ]


@needs_git
def test_the_history_lists_versions_newest_first_and_marks_datalad_runs(mock_project):
    make_dataset(mock_project)
    (mock_project / "rows.txt").write_text("1\n", encoding="utf-8")
    (mock_project / "more.txt").write_text("2\n", encoding="utf-8")
    git(mock_project, "add", "rows.txt", "more.txt")
    message = "[DATALAD RUNCMD] Count the rows\n\n=== Do not change"
    git(mock_project, "commit", "-q", "-m", message)
    [ran, start] = history(mock_project, "main")
    assert (ran.ran, ran.title) == (True, "Count the rows")
    assert sorted(ran.files) == ["more.txt", "rows.txt"]
    assert (start.ran, start.title, start.author) == (False, "Start", "Ada")
    assert ran.when >= start.when
