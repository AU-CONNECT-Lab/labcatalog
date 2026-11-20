import pytest

from labcatalog.datalad.line_endings import (
    add_rules,
    batches,
    convertible,
    keep_line_endings,
)
from labcatalog.exceptions import DataladError
from labcatalog.project import load_project
from tests.test_datalad import git, make_dataset, needs_git

FILES = {
    "raw/made here.csv": b"id,x\r\n1,2\r\n",
    "raw/made elsewhere.csv": b"id,x\n1,2\n",
    "raw/café.csv": b"id,x\n3,4\n",
    "raw/scan.bin": b"\x00\x01\x02\r\n",
}
SCRIPT = "scripts/run.sh"


def converting_dataset(folder):
    root = folder / "lab"
    for name, content in {**FILES, SCRIPT: b"echo hi\n", "raw/x[1].csv": b"id\n1\n"}.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(content)
    git(root, "init", "-b", "main")
    git(root, "config", "core.autocrlf", "true")
    git(root, "add", ".")
    git(root, "commit", "-m", "Start")
    return root


def cloned(root, name: str) -> dict[str, bytes]:
    git(root.parent, "clone", "-c", "core.autocrlf=true", str(root), name)
    return {file: (root.parent / name / file).read_bytes() for file in FILES}


@needs_git
def test_a_clone_has_the_files_a_freeze_records_as_they_are_here(tmp_path):
    root = converting_dataset(tmp_path)
    text = ["raw/café.csv", "raw/made elsewhere.csv", "raw/made here.csv", "raw/x[1].csv"]
    assert convertible(root, ["raw"]) == text
    before = cloned(root, "before")
    assert before["raw/made elsewhere.csv"] == b"id,x\r\n1,2\r\n"

    # Only the file written with CRLF differs from what git took in.
    assert add_rules(root, ["raw"], text) == [".gitattributes", "raw/made here.csv"]
    assert (root / ".gitattributes").read_bytes() == b"/raw/** -text\n"
    git(root, "add", ".gitattributes")
    git(root, "commit", "-m", "Keep line endings as they are")
    assert convertible(root, ["raw"]) == []
    assert cloned(root, "after") == FILES
    # A script no freeze records keeps the line endings git gives each computer.
    assert convertible(root, ["scripts"]) == [SCRIPT]


@needs_git
def test_the_rules_name_each_file_go_last_and_come_once(tmp_path):
    root = converting_dataset(tmp_path)
    (root / ".gitattributes").write_bytes(b"*.csv text")
    names = ["raw/made here.csv", "raw/café.csv", "raw/x[1].csv"]
    add_rules(root, names, names)
    add_rules(root, names, names)
    lines = '*.csv text\n"/raw/made here.csv" -text\n/raw/café.csv -text\n/raw/x\\[1].csv -text\n'
    assert (root / ".gitattributes").read_bytes() == lines.encode()
    assert convertible(root, ["raw"]) == ["raw/made elsewhere.csv"]


@needs_git
def test_line_endings_are_not_kept_while_changes_are_unsaved(mock_project):
    make_dataset(mock_project)
    config = mock_project / "labcatalog.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "# mine\n", encoding="utf-8")
    with pytest.raises(DataladError, match=r"changes not saved yet \(labcatalog.yaml\)"):
        keep_line_endings(load_project(mock_project), "datalad")
    assert not (mock_project / ".gitattributes").exists()


def test_many_names_are_saved_a_command_line_at_a_time():
    long = ["a" * 15000, "b" * 15000, "c"]
    assert list(batches(long)) == [[long[0]], [long[1], long[2]]]
    assert list(batches(["a", "b"])) == [["a", "b"]]
