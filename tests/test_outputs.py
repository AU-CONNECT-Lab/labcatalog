import json
from datetime import datetime

from labcatalog import outputs
from labcatalog.outputs import write_output
from labcatalog.pipeline import run_catalog


def test_output_folder_holds_the_files_and_the_data_manifest(mock_project):
    result = run_catalog(mock_project)
    folder = write_output(mock_project, "correlations", {"a.csv": b"x\n"}, result.manifest)
    assert folder.parent == mock_project / "outputs"
    assert folder.name.endswith("_correlations")
    assert sorted(p.name for p in folder.iterdir()) == ["a.csv", "manifest.json"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert {f["path"] for f in manifest["files"]} >= {"data/parent_w1.csv", "data/child_w1.csv"}


def test_saves_in_the_same_second_get_their_own_folders(mock_project, monkeypatch):
    result = run_catalog(mock_project)
    moment = datetime(2026, 10, 16, 9, 30, 0)
    monkeypatch.setattr(
        outputs, "datetime", type("Fixed", (), {"now": staticmethod(lambda: moment)})
    )
    names = [write_output(mock_project, "t", {}, result.manifest).name for _ in range(3)]
    assert names == ["2026-10-16_093000_t", "2026-10-16_093000_t_2", "2026-10-16_093000_t_3"]
