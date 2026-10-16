import sys
from pathlib import Path

import pytest

from labcatalog.exceptions import EditError
from labcatalog.metadata import new_dataset
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project

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
    assert new_dataset.check(project, found) == []
    new_dataset.write(project, found)
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
    found = [new_dataset.Change("labcatalog.yaml", text)]
    issues = new_dataset.check(project, found)
    assert [i.message.split(" ", 1)[1] for i in issues] == [
        "(child_w9).wave: wave 9 is not listed for study mock_study"
    ]
