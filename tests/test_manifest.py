import os

from labcatalog.data.manifest import build_manifest, changed, file_times, git_commit
from labcatalog.project import EXAMPLE_DIR, load_project
from labcatalog.sources import load_datasets


def manifest_for(root):
    project = load_project(root)
    return build_manifest(project, load_datasets(project))


def test_records_every_data_file(mock_project):
    manifest = manifest_for(mock_project)
    records = {record.dataset: record for record in manifest.files}
    # Nine questionnaire files, twelve from the other modalities, and the roster.
    assert set(records) >= {
        "parent_w1",
        "parent_w2",
        "parent_w3",
        "child_w1",
        "child_w2",
        "child_w3",
    }
    assert len(records) == 22 and "roster_mock_study" in records
    assert records["parent_w1"].path == "data/parent_w1.csv"
    assert records["parent_w1"].rows == 191
    assert len(records["parent_w1"].sha256) == 64
    assert str(records["parent_w1"].snapshot_date) == "2026-10-10"


def test_checksum_changes_when_a_value_changes(mock_project):
    before = {r.dataset: r.sha256 for r in manifest_for(mock_project).files}
    path = mock_project / "data" / "child_w2.csv"
    path.write_text(path.read_text(encoding="utf-8").replace(",2,", ",3,", 1), encoding="utf-8")
    after = {r.dataset: r.sha256 for r in manifest_for(mock_project).files}
    assert before["child_w2"] != after["child_w2"]
    assert before["child_w1"] == after["child_w1"]


def test_file_times_see_what_others_change(mock_project):
    before = file_times(mock_project)
    relative = {p.relative_to(mock_project).as_posix() for p in before}
    assert {"labcatalog.yaml", "data/child_w1.csv", "data/participants.csv"} <= relative
    assert any(r.startswith("instruments/") for r in relative)

    instrument = next(p for p in before if p.parent.name == "instruments")
    os.utime(instrument, ns=(before[instrument] + 10**9, before[instrument] + 10**9))
    (mock_project / "accepted_warnings.yaml").write_text("accepted: []\n", encoding="utf-8")
    assert changed(before, file_times(mock_project)) == sorted(
        [instrument, mock_project / "accepted_warnings.yaml"]
    )


def test_file_times_still_watch_the_folders_when_the_settings_break(mock_project):
    (mock_project / "labcatalog.yaml").write_text("datasets: [", encoding="utf-8")
    relative = {p.relative_to(mock_project).as_posix() for p in file_times(mock_project)}
    assert "labcatalog.yaml" in relative and any(r.startswith("instruments/") for r in relative)


def test_metadata_outside_git_has_no_commit(tmp_path):
    assert git_commit(tmp_path) is None


def test_metadata_inside_git_records_the_commit():
    commit = git_commit(EXAMPLE_DIR)
    assert commit is not None and len(commit.removesuffix("-modified")) >= 7
