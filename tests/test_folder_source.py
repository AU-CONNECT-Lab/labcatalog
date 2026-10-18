import pytest

from labcatalog.data.manifest import build_manifest, file_times
from labcatalog.exceptions import DataSourceError
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project
from labcatalog.sources import load_datasets
from labcatalog.sources.folder_source import file_pattern

SCANS = (
    "  - {name: scans_w1, modality: fmri, study: mock_study, wave: 1, reporter: child, "
    "source: folder, path: bids, files: 'sub-{id}/ses-1/func/*_bold.nii.gz'}\n"
)
FILES = [
    "sub-1001C/ses-1/func/sub-1001C_ses-1_task-rest_run-1_bold.nii.gz",
    "sub-1001C/ses-1/func/sub-1001C_ses-1_task-rest_run-2_bold.nii.gz",
    "sub-1002C/ses-1/func/sub-1002C_ses-1_task-rest_bold.nii.gz",
    "sub-1002C/ses-2/func/sub-1002C_ses-2_task-rest_bold.nii.gz",
    "sub-1003C/ses-1/anat/sub-1003C_ses-1_T1w.nii.gz",
    "README",
]


def add_scans(root, entry: str = SCANS) -> None:
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    assert "datasets:\n" in text
    config.write_text(text.replace("datasets:\n", "datasets:\n" + entry, 1), encoding="utf-8")
    for name in FILES:
        path = root / "bids" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")


def test_each_person_gets_a_count_of_their_matching_files(mock_project):
    add_scans(mock_project)
    project = load_project(mock_project)
    scans = load_datasets(project)["scans_w1"]
    assert scans.frame.to_dict("list") == {scans.id_column: ["1001C", "1002C"], "files": ["2", "1"]}
    assert scans.group.tolist() == ["1001", "1002"]
    assert not [i for i in validate_project(project) if "scans_w1" in i.message]


def test_the_manifest_fingerprints_which_files_are_there(mock_project):
    add_scans(mock_project)
    project = load_project(mock_project)
    record = next(
        f for f in build_manifest(project, load_datasets(project)).files if f.dataset == "scans_w1"
    )
    assert record.path == "bids" and record.rows == 2
    (mock_project / "bids" / "sub-1004C" / "ses-1" / "func").mkdir(parents=True)
    (mock_project / "bids" / "sub-1004C" / "ses-1" / "func" / "run_bold.nii.gz").write_bytes(b"x")
    again = next(
        f for f in build_manifest(project, load_datasets(project)).files if f.dataset == "scans_w1"
    )
    assert again.sha256 != record.sha256 and again.rows == 3


def test_folder_settings_are_checked(mock_project):
    add_scans(mock_project, SCANS.replace("sub-{id}", "sub-x"))
    messages = [i.message for i in validate_project(load_project(mock_project))]
    assert any("files: needs {id} once" in m for m in messages)
    (mock_project / "bids").rename(mock_project / "moved")
    with pytest.raises(DataSourceError, match="scans_w1: folder not found"):
        load_datasets(load_project(mock_project))


def test_only_folder_datasets_take_files(mock_project):
    add_scans(mock_project, SCANS.replace("source: folder", "source: csv"))
    messages = [i.message for i in validate_project(load_project(mock_project))]
    assert any("files: only folder datasets take files" in m for m in messages)


def test_patterns_read_the_id_out_of_a_path():
    pattern = file_pattern("**/sub-{id}_ses-1_?.nii")
    assert pattern.fullmatch("a/b/sub-1001C_ses-1_x.nii").group("id") == "1001C"
    assert pattern.fullmatch("sub-1001C_ses-1_x.nii").group("id") == "1001C"
    assert pattern.fullmatch("sub-1001C_ses-2_x.nii") is None


def test_changes_inside_a_folder_dataset_are_not_watched(mock_project):
    # Such folders may hold thousands of files, too many to look at every few seconds.
    add_scans(mock_project)
    assert not [p for p in file_times(mock_project) if "bids" in p.parts]
