from labcatalog.manifest import build_manifest, git_commit
from labcatalog.project import EXAMPLE_DIR, load_project
from labcatalog.sources import load_datasets


def manifest_for(root):
    project = load_project(root)
    return build_manifest(project, load_datasets(project))


def test_records_every_data_file(mock_project):
    manifest = manifest_for(mock_project)
    records = {record.dataset: record for record in manifest.files}
    assert set(records) == {"parent_w1", "parent_w2", "child_w1", "child_w2"}
    assert records["parent_w1"].path == "data/parent_w1.csv"
    assert records["parent_w1"].rows == 116
    assert len(records["parent_w1"].sha256) == 64
    assert str(records["parent_w1"].snapshot_date) == "2026-10-10"


def test_checksum_changes_when_a_value_changes(mock_project):
    before = {r.dataset: r.sha256 for r in manifest_for(mock_project).files}
    path = mock_project / "data" / "child_w2.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",2,", ",3,", 1), encoding="utf-8")
    after = {r.dataset: r.sha256 for r in manifest_for(mock_project).files}
    assert before["child_w2"] != after["child_w2"]
    assert before["child_w1"] == after["child_w1"]


def test_metadata_outside_git_has_no_commit(tmp_path):
    assert git_commit(tmp_path) is None


def test_metadata_inside_git_records_the_commit():
    commit = git_commit(EXAMPLE_DIR)
    assert commit is not None and len(commit.removesuffix("-modified")) >= 7
