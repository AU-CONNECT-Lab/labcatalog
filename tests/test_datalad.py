import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from labcatalog.ai.scoring import reference_pdfs
from labcatalog.cli import app
from labcatalog.data.check import check_prepare_outputs
from labcatalog.data.ids import load_exclusions
from labcatalog.data.manifest import build_manifest, git_commit
from labcatalog.data.prepare import Session, run_steps, step_states
from labcatalog.datalad.annex import is_placeholder
from labcatalog.datalad.bridge import datalad_status, use_folder
from labcatalog.datalad.check import check_git_annex
from labcatalog.datalad.freeze import differences, push_targets
from labcatalog.exceptions import DataladError, DataSourceError, FreezeError, MetadataError
from labcatalog.metadata.history import file_history
from labcatalog.pipeline import (
    run_catalog,
    run_freeze,
    run_get,
    run_get_missing,
    run_open_freeze,
    run_push_freeze,
)
from labcatalog.project import init_project, load_project
from labcatalog.sources import load_datasets

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

POINTER = "/annex/objects/MD5E-s4126--0f343b0931126a20f133d67c2b018a3b.csv\n"
DATASET_ID = "8a3c6f0e-5d2b-4c1a-9e7f-1b2c3d4e5f60"
DATA_ID = "1f2e3d4c-5b6a-4987-8a1b-2c3d4e5f6a7b"


def git(root, *args: str) -> str:
    identity = ["-c", "user.name=Ada", "-c", "user.email=ada@example.org"]
    done = subprocess.run(
        ["git", "-C", str(root), *identity, *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def make_dataset(root, dataset_id: str = DATASET_ID) -> None:
    (root / ".datalad").mkdir()
    config = f'[datalad "dataset"]\n\tid = {dataset_id}\n'
    (root / ".datalad" / "config").write_text(config, encoding="utf-8")
    git(root, "init", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-m", "Start")


def manifest_for(root):
    project = load_project(root)
    return build_manifest(project, load_datasets(project))


def test_a_data_file_without_its_content_says_how_to_get_it(mock_project):
    (mock_project / "data" / "child_w2.csv").write_text(POINTER, encoding="utf-8")
    expected = r"child_w2: the content of .*child_w2\.csv is not on this computer; get it with: datalad get"
    with pytest.raises(DataSourceError, match=expected):
        load_datasets(load_project(mock_project))

    exclusions = mock_project / "withdrawn.csv"
    exclusions.write_text(POINTER, encoding="utf-8")
    with pytest.raises(DataSourceError, match="Exclusion list: the content of"):
        load_exclusions(exclusions)


def test_placeholders_are_pointer_files_or_broken_annex_links(mock_project):
    assert not is_placeholder(mock_project / "data" / "parent_w1.csv")
    assert not is_placeholder(mock_project / "data" / "absent.csv")
    link = mock_project / "data" / "linked.csv"
    try:
        os.symlink("../.git/annex/objects/Xx/Yy/MD5E-s1--x.csv/MD5E-s1--x.csv", link)
    except OSError:
        pytest.skip("this account cannot make symbolic links")
    assert is_placeholder(link)


def test_prepare_files_without_content_are_not_downloaded_rather_than_present(mock_project):
    (mock_project / "raw" / "parent_w1_export.csv").write_text(POINTER, encoding="utf-8")
    states = {s.step.name: s for s in step_states(load_project(mock_project))}
    raw = states["clean_parent_w1"].inputs[0]
    assert raw.placeholder and raw.modified is None
    assert states["clean_parent_w1"].status == "missing input"
    assert "raw/parent_w1_export.csv" not in {r.path for r in manifest_for(mock_project).inputs}

    (mock_project / "data" / "child_w1.csv").write_text(POINTER, encoding="utf-8")
    issues = check_prepare_outputs(load_project(mock_project))
    [missing] = [i for i in issues if i.code == "prepare_output_missing"]
    assert "clean_child_w1: the content of" in missing.message
    assert "datalad get" in missing.message


def test_no_datalad_record_outside_a_dataset(mock_project):
    assert manifest_for(mock_project).datalad == []


@needs_git
def test_the_manifest_records_the_nearest_dataset_of_each_file(mock_project):
    make_dataset(mock_project / "data", DATA_ID)
    make_dataset(mock_project)
    git(mock_project / "data", "tag", "freeze-2026-06")
    project_head = git(mock_project, "rev-parse", "--short", "HEAD")
    data_head = git(mock_project / "data", "rev-parse", "--short", "HEAD")

    records = {r.path: r for r in manifest_for(mock_project).datalad}
    assert records["."].model_dump() == {
        "path": ".",
        "id": DATASET_ID,
        "commit": project_head,
        "tags": [],
    }
    assert records["data"].model_dump() == {
        "path": "data",
        "id": DATA_ID,
        "commit": data_head,
        "tags": ["freeze-2026-06"],
    }

    path = mock_project / "data" / "child_w2.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",2,", ",3,", 1), encoding="utf-8")
    records = {r.path: r for r in manifest_for(mock_project).datalad}
    assert records["data"].commit == f"{data_head}-modified"
    assert records["."].commit == project_head


@needs_git
def test_on_an_adjusted_branch_the_original_branch_commit_is_recorded(mock_project):
    make_dataset(mock_project)
    git(mock_project, "tag", "plain-tag")
    main = git(mock_project, "rev-parse", "--short", "main")
    git(mock_project, "checkout", "-b", "adjusted/main(unlocked)")
    git(mock_project, "commit", "--allow-empty", "-m", "git-annex adjusted branch")
    git(mock_project, "tag", "version-tag")
    assert git(mock_project, "rev-parse", "--short", "HEAD") != main

    assert git_commit(mock_project) == main
    [record] = manifest_for(mock_project).datalad
    assert record.commit == main
    assert record.tags == ["plain-tag", "version-tag"]

    git(mock_project, "commit", "--allow-empty", "-m", "Plain git commit, not synced")
    assert git_commit(mock_project) == f"{main}-modified"
    assert manifest_for(mock_project).datalad[0].commit == f"{main}-modified"


def test_metadata_without_its_content_says_how_to_get_it(mock_project):
    (mock_project / "instruments" / "example_mood.yaml").write_text(POINTER, encoding="utf-8")
    with pytest.raises(MetadataError) as caught:
        load_project(mock_project)
    [issue] = [i for i in caught.value.issues if i.code == "not_downloaded"]
    assert issue.location == "instruments/example_mood.yaml"
    assert "datalad get" in issue.message


def datalad_exe() -> str | None:
    home_bin = Path.home() / ".local" / "bin"
    return shutil.which("datalad") or shutil.which("datalad", path=str(home_bin))


needs_datalad = pytest.mark.skipif(datalad_exe() is None, reason="DataLad is not installed")


@pytest.fixture
def datalad(monkeypatch):
    exe = datalad_exe()
    # Inside a dataset git itself calls git-annex, so labcatalog's git calls need it on PATH too.
    monkeypatch.setenv("PATH", str(Path(exe).parent) + os.pathsep + os.environ["PATH"])

    def run(root, *args: str) -> str:
        done = subprocess.run([exe, *args], cwd=root, check=True, capture_output=True, text=True)
        return done.stdout

    return run


def shared_commit(root) -> str:
    # The adjusted commit stays on this computer; the one under it is what other clones have.
    adjusted = git(root, "rev-parse", "--abbrev-ref", "HEAD").startswith("adjusted/")
    return git(root, "rev-parse", "--short", "HEAD^" if adjusted else "HEAD")


@needs_datalad
def test_a_real_dataset_and_its_clone_record_the_same_commit(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    # Metadata stays in git, row-level data goes to the annex.
    with (mock_project / ".gitattributes").open("a", encoding="utf-8") as handle:
        handle.write("data/** annex.largefiles=anything\n")
    datalad(mock_project, "save", "-m", "Add the catalog")
    datalad(mock_project, "save", "-m", "Freeze", "--version-tag", "freeze-test")
    commit = shared_commit(mock_project)

    [record] = manifest_for(mock_project).datalad
    assert record.commit == commit
    assert record.tags == ["freeze-test"]

    clone = mock_project.parent / "clone"
    datalad(mock_project.parent, "clone", str(mock_project), str(clone))
    with pytest.raises(DataSourceError, match=r"parent_w1: the content of .* datalad get"):
        load_datasets(load_project(clone))
    states = {s.step.name: s for s in step_states(load_project(clone))}
    assert states["clean_parent_w1"].outputs[0].placeholder

    datalad(clone, "get", "data")
    [cloned] = manifest_for(clone).datalad
    assert cloned.id == record.id
    assert cloned.commit == commit


@needs_datalad
def test_a_plain_git_commit_in_a_real_dataset(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    datalad(mock_project, "save", "-m", "Add the catalog")
    commit = shared_commit(mock_project)
    adjusted = git(mock_project, "rev-parse", "--abbrev-ref", "HEAD").startswith("adjusted/")
    (mock_project / "notes.txt").write_text("checked\n", encoding="utf-8")
    git(mock_project, "add", "notes.txt")
    git(mock_project, "commit", "-m", "Plain git commit")

    [record] = manifest_for(mock_project).datalad
    if adjusted:
        assert record.commit == f"{commit}-modified"
    else:
        assert record.commit == git(mock_project, "rev-parse", "--short", "HEAD")


def test_using_datalad_puts_its_folder_first_on_path_once(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "elsewhere")
    datalad = str(tmp_path / "bin" / "datalad.exe")
    use_folder(datalad)
    use_folder(datalad)
    assert os.environ["PATH"] == os.pathsep.join([str(tmp_path / "bin"), "elsewhere"])


def test_a_wrong_datalad_path_is_explained(tmp_path):
    with pytest.raises(DataladError, match="DataLad not found at .*Settings page"):
        datalad_status(str(tmp_path / "datalad.exe"))


@needs_datalad
def test_the_status_names_datalad_and_git_annex(datalad):
    found = datalad_status(datalad_exe())
    assert found.datalad.startswith("datalad ")
    assert found.annex[0].isdigit()


@needs_git
def test_freezing_data_in_datalad_needs_datalad(mock_project):
    make_dataset(mock_project)
    with pytest.raises(DataladError, match="set the path to datalad on the Settings page"):
        run_freeze(mock_project, "pilot", None)
    assert not (mock_project / "freezes").exists()


def in_tag(root, tag: str, path: str) -> bool:
    done = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{tag}:{path}"])
    return done.returncode == 0


@needs_datalad
def test_a_freeze_saves_and_tags_the_commit_clones_share(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    with (mock_project / ".gitattributes").open("a", encoding="utf-8") as handle:
        handle.write("data/** annex.largefiles=anything\n")
    datalad(mock_project, "save", "-m", "Add the catalog")
    # Annexed files are locked on Linux until unlocked.
    datalad(mock_project, "unlock", "data/child_w2.csv")
    path = mock_project / "data" / "child_w2.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",2,", ",3,", 1), encoding="utf-8")
    (mock_project / "outputs").mkdir()
    (mock_project / "outputs" / "rows.csv").write_text("id\n1\n", encoding="utf-8")

    record_path, record = run_freeze(mock_project, "pilot", datalad_exe())
    assert record.tag == "pilot"
    [frozen] = record.manifest.datalad
    assert not frozen.commit.endswith("-modified")
    assert in_tag(mock_project, "pilot", record_path.relative_to(mock_project).as_posix())
    tagged = git(mock_project, "rev-parse", "--short", "pilot^{commit}")
    assert tagged == shared_commit(mock_project)
    # Exports can hold row-level data, so a freeze leaves them out of the dataset.
    assert git(mock_project, "status", "--porcelain", "--", "outputs") == "?? outputs/"
    assert manifest_for(mock_project).datalad[0].tags == ["pilot"]


@needs_datalad
def test_a_freeze_tags_a_data_subdataset_and_the_dataset_above_it(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    datalad(mock_project, "create", "-d", ".", "--force", "data")
    datalad(mock_project, "save", "-r", "-m", "Add the catalog")
    datalad(mock_project / "data", "unlock", "child_w2.csv")
    path = mock_project / "data" / "child_w2.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",2,", ",3,", 1), encoding="utf-8")

    _, record = run_freeze(mock_project, "pilot", datalad_exe())
    assert {r.path for r in record.manifest.datalad} == {".", "data"}
    assert not any(r.commit.endswith("-modified") for r in record.manifest.datalad)
    data_tag = git(mock_project / "data", "rev-parse", "pilot^{commit}")
    assert git(mock_project, "rev-parse", "pilot:data") == data_tag


CLEAN = """\
import sys
from pathlib import Path
rows = Path("raw/a.csv").read_text().splitlines()
Path("data").mkdir(exist_ok=True)
Path("data/a.csv").write_text(f"{sys.argv[1]} {len(rows)}")
"""


def datalad_steps(tmp_path) -> Path:
    root = init_project(tmp_path / "lab", example=False)
    step = {
        "name": "clean",
        # Braces in the command must reach the script as they are.
        "run": f'"{sys.executable}" scripts/clean.py {{x}}',
        "inputs": ["raw/a.csv", "scripts/clean.py"],
        "outputs": ["data/a.csv"],
    }
    with (root / "labcatalog.yaml").open("a", encoding="utf-8") as file:
        file.write(f"prepare_with: datalad\nprepare: {json.dumps([step])}\n")
    (root / "raw").mkdir()
    (root / "raw" / "a.csv").write_text("id,x\n1,2\n2,3\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "clean.py").write_text(CLEAN, encoding="utf-8")
    return root


def test_steps_set_to_run_with_datalad_need_datalad(tmp_path):
    root = datalad_steps(tmp_path)
    session = Session()
    with pytest.raises(DataladError, match="set the path to datalad on the Settings page"):
        run_steps(load_project(root), ["clean"], session)
    assert session.runs == {}


def last_run_record(root) -> tuple[str, dict]:
    adjusted = git(root, "rev-parse", "--abbrev-ref", "HEAD").startswith("adjusted/")
    message = git(root, "log", "-1", "--format=%B", "HEAD^" if adjusted else "HEAD")
    record = message.split("=== Do not change lines below ===")[1].split("^^^")[0]
    return message.splitlines()[0], json.loads(record)


@needs_datalad
def test_steps_run_with_datalad_are_recorded_and_get_their_inputs(tmp_path, datalad):
    root = datalad_steps(tmp_path)
    datalad(root, "create", "-c", "text2git", "--force", ".")
    with (root / ".gitattributes").open("a", encoding="utf-8") as handle:
        handle.write("raw/** annex.largefiles=anything\ndata/** annex.largefiles=anything\n")
    datalad(root, "save", "-m", "Add the catalog")

    [run] = run_steps(load_project(root), ["clean"], Session(), datalad=datalad_exe())
    assert run.exit_code == 0, run.log
    assert (root / "data" / "a.csv").read_text(encoding="utf-8") == "{x} 3"
    subject, record = last_run_record(root)
    assert subject == "[DATALAD RUNCMD] clean"
    assert record["inputs"] == ["raw/a.csv", "scripts/clean.py"]
    assert record["outputs"] == ["data/a.csv"]
    assert git(root, "status", "--porcelain", "--", "data") == ""

    clone = tmp_path / "clone"
    datalad(tmp_path, "clone", str(root), str(clone))
    assert is_placeholder(clone / "raw" / "a.csv")
    [run] = run_steps(load_project(clone), ["clean"], Session(), datalad=datalad_exe())
    assert run.exit_code == 0, run.log
    assert not is_placeholder(clone / "raw" / "a.csv")
    assert (clone / "data" / "a.csv").read_text(encoding="utf-8") == "{x} 3"


def test_a_missing_git_annex_is_reported_only_for_datalad_projects(mock_project, monkeypatch):
    monkeypatch.setattr("labcatalog.datalad.check.shutil.which", lambda name: None)
    assert check_git_annex(load_project(mock_project)) == []
    (mock_project / ".datalad").mkdir()
    (mock_project / ".datalad" / "config").write_text("", encoding="utf-8")
    [issue] = check_git_annex(load_project(mock_project))
    assert issue.code == "git_annex_not_found"


def test_references_without_their_content_say_how_to_get_them(mock_project):
    pdf = mock_project / "references" / "example_mood.pdf"
    pdf.write_text(POINTER, encoding="utf-8")
    project = load_project(mock_project)
    assert reference_pdfs(project, project.instruments["example_mood"]) == []

    (mock_project / "references" / "references.bib").write_text(POINTER, encoding="utf-8")
    with pytest.raises(MetadataError) as caught:
        load_project(mock_project)
    [issue] = [i for i in caught.value.issues if i.code == "not_downloaded"]
    assert issue.location == "references/references.bib"


@needs_datalad
def test_get_missing_content_fetches_what_a_clone_lacks(mock_project, datalad):
    # Without text2git even the metadata are in the annex.
    datalad(mock_project, "create", "--force", ".")
    datalad(mock_project, "save", "-m", "Add the catalog")
    clone = mock_project.parent / "clone"
    datalad(mock_project.parent, "clone", str(mock_project), str(clone))
    with pytest.raises(MetadataError):
        load_project(clone)

    run_get_missing(clone, datalad_exe())
    result = run_catalog(clone)
    assert result.project is not None
    assert result.datasets
    # Reference PDFs wait until someone opens them.
    pdf = clone / "references" / "example_mood.pdf"
    assert is_placeholder(pdf)
    run_get([pdf], datalad_exe())
    assert not is_placeholder(pdf)


@needs_datalad
def test_history_works_in_a_real_dataset(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    datalad(mock_project, "save", "-m", "Add the catalog")
    path = "instruments/example_mood.yaml"
    with (mock_project / path).open("a", encoding="utf-8") as handle:
        handle.write("# checked\n")

    uncommitted, committed = file_history(mock_project, path)
    assert uncommitted.message == "Uncommitted changes"
    assert "+# checked" in uncommitted.diff
    assert committed.message == "Add the catalog"


def test_a_record_only_freeze_cannot_be_opened(mock_project):
    run_freeze(mock_project, "pilot", None)
    with pytest.raises(FreezeError, match="pilot is only a record"):
        run_open_freeze(mock_project, "pilot", "datalad")


def change_child_w2(root, datalad) -> None:
    datalad(root / "data", "unlock", "child_w2.csv")
    path = root / "data" / "child_w2.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",2,", ",3,", 1), encoding="utf-8")


@needs_datalad
def test_an_opened_freeze_has_the_frozen_data(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    with (mock_project / ".gitattributes").open("a", encoding="utf-8") as handle:
        handle.write("data/** annex.largefiles=anything\n")
    datalad(mock_project, "save", "-m", "Add the catalog")
    _, record = run_freeze(mock_project, "pilot", datalad_exe())
    change_child_w2(mock_project, datalad)
    datalad(mock_project, "save", "-m", "Later change")

    copy = run_open_freeze(mock_project, "pilot", datalad_exe())
    assert differences(record, run_catalog(copy).manifest) == []
    assert differences(record, run_catalog(mock_project).manifest) == ["child_w2"]


@needs_datalad
def test_an_opened_freeze_installs_its_subdatasets_at_the_tag(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    datalad(mock_project, "create", "-d", ".", "--force", "data")
    datalad(mock_project, "save", "-r", "-m", "Add the catalog")
    _, record = run_freeze(mock_project, "pilot", datalad_exe())
    change_child_w2(mock_project, datalad)
    datalad(mock_project, "save", "-r", "-m", "Later change")

    copy = run_open_freeze(mock_project, "pilot", datalad_exe())
    assert differences(record, run_catalog(copy).manifest) == []


@needs_datalad
def test_a_pushed_freeze_opens_from_another_clone(mock_project, datalad, tmp_path):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    with (mock_project / ".gitattributes").open("a", encoding="utf-8") as handle:
        handle.write("data/** annex.largefiles=anything\n")
    datalad(mock_project, "save", "-m", "Add the catalog")
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "store.git")], check=True)
    # A relative URL would be copied as it is into clones, where it no longer points at the store.
    store = (tmp_path / "store.git").as_posix()
    datalad(mock_project, "siblings", "add", "-s", "store", "--url", store)
    datalad(mock_project, "push", "--to", "store")
    _, record = run_freeze(mock_project, "pilot", datalad_exe())
    assert run_push_freeze(mock_project, "pilot", datalad_exe()) == [mock_project.resolve()]
    change_child_w2(mock_project, datalad)
    datalad(mock_project, "save", "-m", "Later change")
    datalad(mock_project, "push", "--to", "store")

    (tmp_path / "elsewhere").mkdir()
    datalad(tmp_path / "elsewhere", "clone", store, "lab")
    copy = run_open_freeze(tmp_path / "elsewhere" / "lab", "pilot", datalad_exe())
    assert differences(record, run_catalog(copy).manifest) == []


@needs_git
def test_a_freeze_pushes_to_the_only_sibling_or_to_origin(tmp_path):
    roots = []
    for name, remotes in [
        ("none", []),
        ("one", ["store"]),
        ("origin", ["store", "origin"]),
        ("two", ["a", "b"]),
    ]:
        root = tmp_path / name
        root.mkdir()
        git(root, "init", "-q")
        for remote in remotes:
            git(root, "remote", "add", remote, str(tmp_path / "elsewhere.git"))
        roots.append(root)
    assert list(push_targets(roots).values()) == [None, "store", "origin", None]


def test_the_command_line_needs_datalad_and_a_known_freeze(mock_project, monkeypatch):
    run_freeze(mock_project, "pilot", None)
    with pytest.raises(FreezeError, match="No freeze named pliot; the freezes are: pilot"):
        run_open_freeze(mock_project, "pliot", "datalad")
    monkeypatch.setattr(shutil, "which", lambda name, **kwargs: None)
    done = CliRunner().invoke(app, ["get", "-p", str(mock_project)])
    assert isinstance(done.exception, DataladError)


@needs_datalad
def test_the_command_line_gets_content_and_opens_a_freeze(mock_project, datalad):
    datalad(mock_project, "create", "-c", "text2git", "--force", ".")
    with (mock_project / ".gitattributes").open("a", encoding="utf-8") as handle:
        handle.write("data/** annex.largefiles=anything\n")
    datalad(mock_project, "save", "-m", "Add the catalog")
    run_freeze(mock_project, "pilot", datalad_exe())
    clone = mock_project.parent / "clone"
    datalad(mock_project.parent, "clone", str(mock_project), str(clone))
    assert is_placeholder(clone / "data" / "child_w2.csv")
    runner = CliRunner()
    done = runner.invoke(app, ["get", "-p", str(clone)])
    assert done.exit_code == 0, done.output
    assert not is_placeholder(clone / "data" / "child_w2.csv")
    frozen = mock_project.parent / "frozen"
    done = runner.invoke(
        app, ["open-freeze", "pilot", "--to", str(frozen), "-p", str(mock_project)]
    )
    assert done.exit_code == 0, done.output
    assert done.output.strip() == f"Opened pilot in {frozen}"
    assert run_catalog(frozen).datasets
