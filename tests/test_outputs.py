import json

from labcatalog.gui.common import col
from labcatalog.outputs import table_csv, write_output
from labcatalog.pipeline import run_catalog


def test_output_folder_holds_the_files_and_the_data_manifest(mock_project):
    result = run_catalog(mock_project)
    folder = write_output(mock_project, "correlations", {"a.csv": b"x\n"}, result.manifest)
    assert folder.parent == mock_project / "outputs"
    assert folder.name.endswith("_correlations")
    assert sorted(p.name for p in folder.iterdir()) == ["a.csv", "manifest.json"]
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert {f["path"] for f in manifest["files"]} >= {"data/parent_w1.csv", "data/child_w1.csv"}


def test_table_csv_uses_the_column_labels_and_opens_in_excel():
    columns = [col("variable", "Variable"), col("d0", "Parent, wave 1")]
    content = table_csv(columns, [{"variable": "Mood", "d0": "1.20 (0.40)"}, {"variable": "N"}])
    assert content.startswith(b"\xef\xbb\xbf")
    assert content.decode("utf-8-sig").splitlines() == [
        'Variable,"Parent, wave 1"',
        "Mood,1.20 (0.40)",
        "N,",
    ]
