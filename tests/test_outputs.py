import json

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
