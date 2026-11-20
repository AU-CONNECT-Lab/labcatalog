import json
from datetime import datetime

from labcatalog.pipeline import run_catalog
from labcatalog.reports import outputs
from labcatalog.reports.outputs import write_output
from tests.test_datalad import git, needs_git


def test_output_folder_holds_the_files_and_the_data_manifest(mock_project):
    result = run_catalog(mock_project)
    folder = write_output(mock_project, "correlations", {"a.csv": b"x\n"}, result.manifest)
    assert folder.parent == mock_project / "outputs"
    assert folder.name.endswith("_correlations")
    assert sorted(p.name for p in folder.iterdir()) == ["a.csv", "manifest.json"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert {f["path"] for f in manifest["files"]} >= {"data/parent_w1.csv", "data/child_w1.csv"}


@needs_git
def test_git_leaves_what_is_saved_out(mock_project):
    git(mock_project, "init", "-q", "-b", "main")
    files = {"data_by_id.csv": b"id\n1\n"}
    write_output(mock_project, "export", files, run_catalog(mock_project).manifest)
    assert "outputs/" not in git(mock_project, "status", "--porcelain", "--untracked-files=all")


def test_saves_in_the_same_second_get_their_own_folders(mock_project, monkeypatch):
    result = run_catalog(mock_project)
    moment = datetime(2026, 10, 16, 9, 30, 0)
    monkeypatch.setattr(
        outputs, "datetime", type("Fixed", (), {"now": staticmethod(lambda: moment)})
    )
    names = [write_output(mock_project, "t", {}, result.manifest).name for _ in range(3)]
    assert names == ["2026-10-16_093000_t", "2026-10-16_093000_t_2", "2026-10-16_093000_t_3"]
