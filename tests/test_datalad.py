import os
import shutil
import subprocess

import pytest

from labcatalog.annex import is_placeholder
from labcatalog.check import check_prepare_outputs
from labcatalog.exceptions import DataSourceError
from labcatalog.ids import load_exclusions
from labcatalog.manifest import build_manifest, git_commit
from labcatalog.prepare import step_states
from labcatalog.project import load_project
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
    git(mock_project, "tag", "freeze-2026-06")
    main = git(mock_project, "rev-parse", "--short", "main")
    git(mock_project, "checkout", "-b", "adjusted/main(unlocked)")
    git(mock_project, "commit", "--allow-empty", "-m", "git-annex adjusted branch")
    assert git(mock_project, "rev-parse", "--short", "HEAD") != main

    assert git_commit(mock_project) == main
    [record] = manifest_for(mock_project).datalad
    assert record.commit == main
    assert record.tags == ["freeze-2026-06"]
