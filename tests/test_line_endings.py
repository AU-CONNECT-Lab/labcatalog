from labcatalog.datalad.line_endings import add_rule, batches, convertible
from tests.test_datalad import git, needs_git

FILES = {
    "raw/made here.csv": b"id,x\r\n1,2\r\n",
    "raw/made elsewhere.csv": b"id,x\n1,2\n",
    "raw/café.csv": b"id,x\n3,4\n",
    "raw/scan.bin": b"\x00\x01\x02\r\n",
}


def converting_dataset(folder):
    root = folder / "lab"
    for name, content in FILES.items():
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
def test_a_clone_has_the_files_as_they_are_here_once_line_endings_are_kept(tmp_path):
    root = converting_dataset(tmp_path)
    text = ["raw/café.csv", "raw/made elsewhere.csv", "raw/made here.csv"]
    assert convertible(root, ["raw"]) == text
    before = cloned(root, "before")
    assert before["raw/made elsewhere.csv"] == b"id,x\r\n1,2\r\n"

    # Only the file written with CRLF differs from what git took in.
    assert add_rule(root) == [".gitattributes", "raw/made here.csv"]
    assert (root / ".gitattributes").read_bytes() == b"* -text\n"
    git(root, "add", ".gitattributes")
    git(root, "commit", "-m", "Keep line endings as they are")
    assert convertible(root, ["raw"]) == []
    assert cloned(root, "after") == FILES


@needs_git
def test_the_rule_goes_last_and_only_once(tmp_path):
    root = converting_dataset(tmp_path)
    (root / ".gitattributes").write_bytes(b"*.csv text")
    add_rule(root)
    add_rule(root)
    assert (root / ".gitattributes").read_bytes() == b"*.csv text\n* -text\n"
    assert convertible(root, ["raw"]) == []


def test_many_names_are_saved_a_command_line_at_a_time():
    long = ["a" * 15000, "b" * 15000, "c"]
    assert list(batches(long)) == [[long[0]], [long[1], long[2]]]
    assert list(batches(["a", "b"])) == [["a", "b"]]
