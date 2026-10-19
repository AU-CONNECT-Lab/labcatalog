from labcatalog.metadata.folder_rules import (
    BY_PATTERN,
    Field,
    count_folder,
    id_field,
    path_fields,
    suggest,
)
from labcatalog.metadata.new_dataset import roster_ids
from labcatalog.project import load_project

BIDS = [
    "dataset_description.json",
    "participants.tsv",
    "sub-01/ses-1/eeg/sub-01_ses-1_task-rest_eeg.edf",
    "sub-01/ses-1/eeg/sub-01_ses-1_task-rest_eeg.json",
    "sub-01/ses-1/eeg/sub-01_ses-1_task-faces_run-1_eeg.edf",
    "sub-01/ses-1/eeg/sub-01_ses-1_task-faces_run-2_eeg.edf",
    "sub-01/ses-2/eeg/sub-01_ses-2_task-rest_eeg.edf",
    "sub-02/ses-1/eeg/sub-02_ses-1_task-rest_eeg.edf",
    "sub-02/ses-1/eeg/sub-02_ses-1_task-rest_eeg.json",
    "sub-03/ses-2/eeg/sub-03_ses-2_task-rest_eeg.edf",
]


def test_the_fields_in_the_paths_are_found_with_how_many_values_each_takes():
    fields = path_fields(BIDS)
    assert {f.key: f.values for f in fields} == {"sub": 3, "ses": 2, "task": 2, "run": 2}
    assert id_field(fields, None) == "sub"
    assert id_field([Field("participant", 3)], None) == "participant"
    assert id_field([], r"\d{4}C") == BY_PATTERN


def test_rules_keep_this_wave_and_count_each_kind_of_file():
    rules = suggest(BIDS, "sub", "1")
    assert [(r.files, r.people, r.count) for r in rules] == [
        ("sub-{id}/ses-1/eeg/sub-*_ses-1_task-*_eeg.edf", 2, 4),
        ("sub-{id}/ses-1/eeg/sub-*_ses-1_task-*_eeg.json", 2, 2),
        ("sub-{id}/ses-1/eeg/sub-*_ses-1_task-*_run-*_eeg.edf", 1, 2),
    ]
    assert suggest(BIDS, "sub", "2")[0].files == "sub-{id}/ses-2/eeg/sub-*_ses-2_task-*_eeg.edf"


def test_a_field_some_names_leave_out_is_a_wildcard_and_a_run_is_not_a_wave():
    paths = [
        "sub-1/ses-1/func/sub-1_task-a_run-1_bold.nii",
        "sub-1/ses-1/func/sub-1_task-a_run-2_bold.nii",
        "sub-2/ses-1/func/sub-2_task-a_bold.nii",
    ]
    assert [(r.files, r.people, r.count) for r in suggest(paths, "sub", "1")] == [
        ("sub-{id}/ses-1/func/sub-*_task-a*_bold.nii", 2, 3),
        ("sub-{id}/ses-1/func/sub-*_task-a_run-*_bold.nii", 1, 2),
        ("sub-{id}/ses-1/func/sub-*_task-a_bold.nii", 1, 1),
    ]


def test_without_fields_the_id_is_the_part_that_matches_the_pattern():
    paths = ["sessions.csv", "1001C_fixations.csv", "1002C_fixations.csv", "1002C_notes.txt"]
    rules = suggest(paths, BY_PATTERN, "1", r"\d{4}C")
    assert [(r.files, r.people) for r in rules] == [
        ("{id}_fixations.csv", 2),
        ("{id}_notes.txt", 1),
    ]


def test_the_count_shows_repeats_and_ids_the_roster_does_not_know():
    rule = "sub-{id}/ses-1/eeg/*_eeg.edf"
    seen = count_folder(BIDS, rule, roster={"01", "04", "05"}, pattern=r"0[0-3]")
    assert (seen.people, seen.files) == (2, 4)
    assert seen.repeated == {"01": 3}
    assert seen.not_in_roster == ["02"]
    assert seen.roster_without_files == 2
    assert seen.off_pattern == []
    assert "participants.tsv" in seen.unmatched


def test_the_roster_is_narrowed_to_the_dataset_s_reporter(mock_project):
    project = load_project(mock_project)
    children = roster_ids(project, "mock_study", "child")
    assert children and all(i.endswith("C") for i in children)
    assert roster_ids(project, "mock_study", "parent").isdisjoint(children)
