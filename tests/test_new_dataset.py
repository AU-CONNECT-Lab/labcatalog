import sys
from pathlib import Path

import pytest

from labcatalog.exceptions import EditError
from labcatalog.metadata import changes, new_dataset, studies
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project
from labcatalog.sources import load_datasets

PYTHON = Path(sys.executable).as_posix()


@pytest.fixture
def project_root(mock_project):
    # Steps call "python", which need not be on PATH where the tests run.
    config = mock_project / "labcatalog.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("run: python ", f"run: {PYTHON} "),
        encoding="utf-8",
    )
    return mock_project


@pytest.fixture
def export(project_root, tmp_path):
    # Next wave's export: the same survey with the columns renamed for wave 4.
    lines = (project_root / "raw/child_w3_export.csv").read_text(encoding="utf-8-sig").splitlines()
    lines[0] = lines[0].replace("_w3", "_w4")
    path = tmp_path / "downloads" / "Child survey wave 4.csv"
    path.parent.mkdir()
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_a_new_wave_follows_its_template_into_every_file(project_root, export):
    project = load_project(project_root)
    # Datasets cut from a pipeline's folder are left out.
    usable = new_dataset.templates(project)
    assert usable[-1] == "child_w3" and "eeg_w3" not in usable
    draft = new_dataset.suggest(project, "child_w3")
    assert (draft.name, draft.wave) == ("child_w4", "4")
    new_dataset.check_draft(project, draft)
    placement = new_dataset.place(project, draft, export)
    assert (placement.copy_to, placement.data_path) == (
        "raw/child_w4_export.csv",
        "data/child_w4.csv",
    )
    assert placement.step.name == "clean_child_w4"
    assert "raw/child_w4_export.csv data/child_w4.csv" in placement.step.run

    brought = new_dataset.bring_in(project, export, placement)
    assert brought.run.exit_code == 0, brought.run.log
    assert brought.created == ["raw/child_w4_export.csv", "data/child_w4.csv"]
    dataset = new_dataset.dataset_config(project, draft, placement)
    rows = new_dataset.match_columns(project, dataset)
    assert {"column": "ems_1_w4", "instrument": "example_mood", "item": "ems_1"} in rows
    assert new_dataset.coverage(project, "child_w3", rows)["example_mood"] == (9, 9)
    assert new_dataset.check_rows(project, rows) == []

    found = new_dataset.changes(project, draft, placement, rows)
    assert changes.check(project, found) == []
    changes.write(project, found)
    after = load_project(project_root)
    assert validate_project(after) == []
    assert "4" in after.config.studies["mock_study"].waves
    added = next(d for d in after.config.datasets if d.name == "child_w4")
    assert (added.wave, added.reporter, added.path) == ("4", "child", "data/child_w4.csv")
    assert any(s.name == "clean_child_w4" for s in after.config.prepare)
    mood = next(
        a for a in after.studies["mock_study"].administrations if a.instrument == "example_mood"
    )
    assert mood.datasets[-1] == "child_w4" and mood.target == "self"
    assert any(e.column == "ems_9_w4" and e.item == "ems_9" for e in after.maps["child_w4"])
    # Untouched lines stay as they were.
    before = (project_root / "studies/mock_study.yaml").read_text(encoding="utf-8")
    assert "{instrument: eeg_resting, datasets: [eeg_w1, eeg_w3], target: self}" in before


def test_a_dataset_that_repeats_none_starts_a_new_study(project_root, tmp_path):
    changes.write(
        load_project(project_root), studies.new_study(load_project(project_root), "pilot", "Pilot")
    )
    project = load_project(project_root)
    source = tmp_path / "pilot.csv"
    items = [f"ems_{n}" for n in range(1, 10)]
    rows = [
        ",".join(["pid", "visit_date", *items]),
        ",".join(["9001C", "2027-01-20", *"123412341"]),
    ]
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    draft = new_dataset.suggest_blank(project, "pilot")
    assert (draft.wave, draft.blank.modality, draft.blank.reporter) == (
        "1",
        "questionnaire",
        "parent",
    )
    draft.name, draft.blank.reporter = "pilot_child_w1", "child"
    new_dataset.check_draft(project, draft)
    placement = new_dataset.place(project, draft, source)
    assert (placement.copy_to, placement.step) == ("data/pilot_child_w1.csv", None)
    new_dataset.bring_in(project, source, placement)
    dataset = new_dataset.dataset_config(project, draft, placement)
    assert new_dataset.file_columns(project, dataset)[:2] == ["pid", "visit_date"]
    draft.blank.id_column, draft.blank.date_column = "pid", "visit_date"
    matched = new_dataset.match_columns(
        project, new_dataset.dataset_config(project, draft, placement)
    )
    assert new_dataset.coverage(project, "", matched) == {"example_mood": (9, 9)}
    found = new_dataset.changes(project, draft, placement, matched)
    assert changes.check(project, found) == []
    changes.write(project, found)
    config = (project_root / "labcatalog.yaml").read_text(encoding="utf-8")
    # The usual ID column is left out, and the study's new wave goes before the next section.
    assert (
        "  - {name: pilot_child_w1, modality: questionnaire, study: pilot, wave: 1, reporter: child, "
        "source: csv, path: data/pilot_child_w1.csv, date_column: visit_date, snapshot_date: "
    ) in config
    assert "    label: Pilot\n    waves:\n      1: {}\n\n# One entry per data file" in config
    after = load_project(project_root)
    assert after.studies["pilot"].administrations[0].datasets == ["pilot_child_w1"]


def test_a_folder_of_files_is_read_in_place(project_root):
    for name in [
        "sub-2001C/ses-1/func/sub-2001C_task-rest_run-1_bold.nii.gz",
        "sub-2001C/ses-1/func/sub-2001C_task-rest_run-2_bold.nii.gz",
        "sub-2002C/ses-1/func/sub-2002C_task-rest_bold.nii.gz",
        "sub-2002C/ses-1/anat/sub-2002C_T1w.nii.gz",
        "README",
    ]:
        path = project_root / "bids" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    project = load_project(project_root)
    paths = new_dataset.folder_files(project_root / "bids")
    rule = "sub-{id}/ses-1/func/*_bold.nii.gz"
    seen = new_dataset.preview_folder(paths, rule)
    assert (seen.people, seen.files) == (2, 3)
    assert seen.unmatched == ["README", "sub-2002C/ses-1/anat/sub-2002C_T1w.nii.gz"]
    with pytest.raises(EditError, match="put {id} once"):
        new_dataset.preview_folder(paths, "sub-*/ses-1/func/*_bold.nii.gz")

    draft = new_dataset.suggest_blank(project, "mock_study")
    draft.name, draft.blank.modality, draft.blank.reporter = "scans_w1", "fmri", "child"
    draft.files = rule
    new_dataset.check_draft(project, draft)
    placement = new_dataset.place(project, draft, project_root / "bids")
    assert (placement.copy_to, placement.data_path) == (None, "bids")
    assert new_dataset.place(project, draft, Path("~/scans")).data_path == "~/scans"
    found = new_dataset.changes(project, draft, placement, [])
    assert [c.path for c in found] == ["labcatalog.yaml"]
    assert changes.check(project, found) == []
    changes.write(project, found)
    config = (project_root / "labcatalog.yaml").read_text(encoding="utf-8")
    assert (
        "  - {name: scans_w1, modality: fmri, study: mock_study, wave: 1, reporter: child, "
        "source: folder, path: bids, files: 'sub-{id}/ses-1/func/*_bold.nii.gz', snapshot_date: "
    ) in config
    after = load_project(project_root)
    scans = load_datasets(after)["scans_w1"]
    assert scans.frame["files"].tolist() == ["2", "1"]
    assert not [i for i in validate_project(after) if "scans_w1" in i.message]


def test_a_folder_dataset_is_repeated_for_the_next_wave(project_root):
    test_a_folder_of_files_is_read_in_place(project_root)
    for name in ["sub-2001C/ses-2/func/sub-2001C_task-rest_bold.nii.gz"]:
        path = project_root / "bids" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    project = load_project(project_root)
    assert "scans_w1" in new_dataset.templates(project)
    draft = new_dataset.suggest(project, "scans_w1")
    assert (draft.name, draft.wave, draft.files) == (
        "scans_w2",
        "2",
        "sub-{id}/ses-2/func/*_bold.nii.gz",
    )
    placement = new_dataset.place(project, draft, Path("bids"))
    found = new_dataset.changes(project, draft, placement, [])
    assert [c.path for c in found] == ["labcatalog.yaml"]
    assert changes.check(project, found) == []
    changes.write(project, found)
    config = (project_root / "labcatalog.yaml").read_text(encoding="utf-8")
    # The files rule keeps its place among the template's keys.
    assert (
        "  - {name: scans_w2, modality: fmri, study: mock_study, wave: 2, reporter: child, "
        "source: folder, path: bids, files: 'sub-{id}/ses-2/func/*_bold.nii.gz', snapshot_date: "
    ) in config
    scans = load_datasets(load_project(project_root))["scans_w2"]
    assert scans.frame["files"].tolist() == ["1"]


def test_cancelling_removes_only_what_the_wizard_made(project_root, export):
    project = load_project(project_root)
    draft = new_dataset.suggest(project, "child_w3")
    placement = new_dataset.place(project, draft, export)
    brought = new_dataset.bring_in(project, export, placement)
    new_dataset.remove(project, brought.created)
    assert not (project_root / "raw/child_w4_export.csv").exists()
    assert not (project_root / "data/child_w4.csv").exists()
    assert (project_root / "data/child_w3.csv").exists()


def test_refusals(project_root, export):
    project = load_project(project_root)
    draft = new_dataset.suggest(project, "child_w3")
    with pytest.raises(EditError, match="already exists"):
        new_dataset.check_draft(
            project, new_dataset.Draft("child_w3", "child_w2", "4", draft.snapshot_date)
        )
    with pytest.raises(EditError, match="lower-case"):
        new_dataset.check_draft(
            project, new_dataset.Draft("child_w3", "Child 4", "4", draft.snapshot_date)
        )
    (project_root / "data/child_w4.csv").write_text("pid\n", encoding="utf-8")
    with pytest.raises(EditError, match="data/child_w4.csv already exists"):
        new_dataset.place(project, draft, export)
    # Made from a pipeline's folder, so there is no one file to copy in.
    with pytest.raises(EditError, match="extract_eeg_w3"):
        new_dataset.place(project, new_dataset.suggest(project, "eeg_w3"), export)
    rows = [{"column": "x", "instrument": "example_mood", "item": "ems_99"}]
    assert new_dataset.check_rows(project, rows) == ["x: example_mood has no item ems_99"]


def test_renamed_matches_whole_names_only():
    assert new_dataset.renamed("raw/child_w3_export.csv", "child_w3", "child_w4") == (
        "raw/child_w4_export.csv"
    )
    assert new_dataset.renamed("data/child_w30.csv", "child_w3", "child_w4") == "data/child_w30.csv"


def test_problems_across_files_are_caught_before_writing(project_root):
    project = load_project(project_root)
    config = (project_root / "labcatalog.yaml").read_text(encoding="utf-8")
    line = "  - {name: child_w9, modality: questionnaire, study: mock_study, wave: 9, reporter: child, source: csv, path: data/child_w9.csv}\n"
    text = config.replace("datasets:\n", "datasets:\n" + line, 1)
    found = [changes.Change("labcatalog.yaml", text)]
    issues = changes.check(project, found)
    assert [i.message.split(" ", 1)[1] for i in issues] == [
        "(child_w9).wave: wave 9 is not listed for study mock_study"
    ]
