import pytest
import yaml

from labcatalog.config import PrepareStep
from labcatalog.exceptions import EditError
from labcatalog.metadata import changes
from labcatalog.metadata.browse import row_matches
from labcatalog.metadata.scripts import (
    UNUSED,
    entries,
    new_script,
    project_scripts,
    remove_step_change,
    script_index,
    script_of,
    step_change,
)
from labcatalog.metadata.stage_scripts import stage_script
from labcatalog.project import load_project


def test_scripts_are_listed_with_the_steps_that_run_them(mock_project):
    (mock_project / "scripts" / "draft.R").write_text("x <- 1\n", encoding="utf-8")
    (mock_project / "scripts" / "notes.txt").write_text("not a script\n", encoding="utf-8")
    found = project_scripts(load_project(mock_project))
    by_path = {s.path: s for s in found.steps}
    assert len(by_path["scripts/clean_export.R"].steps) == 9
    assert [s.name for s in by_path["scripts/extract_fmri.py"].steps] == [
        "extract_fmri_w1",
        "extract_fmri_w3",
    ]
    assert found.unused == ["scripts/draft.R"]
    assert found.commands == []
    assert (
        script_of(mock_project, PrepareStep(name="x", run="datalad get data", outputs=[])) is None
    )


def test_a_step_is_added_renamed_and_removed(mock_project):
    project = load_project(mock_project)
    path = new_script(mock_project, "tidy", "r")
    assert path == "scripts/tidy.R"
    assert "commandArgs" in (mock_project / path).read_text(encoding="utf-8")
    with pytest.raises(EditError, match="already exists"):
        new_script(mock_project, "tidy", "r")
    with pytest.raises(EditError, match="lower-case"):
        new_script(mock_project, "Tidy up", "python")
    step = PrepareStep(
        name="tidy",
        run="Rscript scripts/tidy.R raw/a.csv data/a.csv",
        inputs=[path],
        outputs=["data/tidy.csv"],
    )
    change = step_change(project, None, step)
    assert changes.check(project, [change]) == []
    changes.write(project, [change])
    project = load_project(mock_project)
    assert project.config.prepare[-1].name == "tidy"
    renamed = step.model_copy(update={"name": "tidy_a"})
    changes.write(project, [step_change(project, "tidy", renamed)])
    project = load_project(mock_project)
    assert [s.name for s in project.config.prepare].count("tidy_a") == 1
    with pytest.raises(EditError, match="already named"):
        step_change(project, "tidy_a", renamed.model_copy(update={"name": "clean_child_w1"}))
    changes.write(project, [remove_step_change(project, "tidy_a")])
    data = yaml.safe_load((mock_project / "labcatalog.yaml").read_text(encoding="utf-8"))
    assert "tidy_a" not in {s["name"] for s in data["prepare"]}


def test_scripts_are_filtered_by_what_their_steps_write(mock_project):
    (mock_project / "scripts" / "draft.R").write_text("x <- 1\n", encoding="utf-8")
    project = load_project(mock_project)
    listed = entries(project, project_scripts(project))
    statuses = {
        s.name: "outdated" if s.name == "extract_fmri_w1" else "up to date"
        for s in project.config.prepare
    }
    index = script_index(project, listed, statuses)
    assert row_matches(index, {"modality": {"fmri"}}) == [
        "scripts/extract_fmri.py",
        "scripts/draft.R",
    ]
    assert row_matches(index, {"status": {"outdated"}}) == ["scripts/extract_fmri.py"]
    assert row_matches(index, {"stage": {UNUSED}}) == ["scripts/draft.R"]
    assert "scripts/draft.R" in row_matches(index, {"language": {"r"}})
    assert "scripts/extract_fmri.py" not in row_matches(index, {"language": {"r"}})
    assert row_matches(index, {}, "parent_w2_export") == ["scripts/clean_export.R"]
    clean = next(e for e in listed if e.key == "scripts/clean_export.R")
    assert {
        project_dataset.study
        for project_dataset in project.config.datasets
        if project_dataset.name in clean.datasets
    } == {"mock_study"}


def test_a_stage_script_says_what_it_reads_and_writes_and_comes_with_its_step(mock_project):
    project = load_project(mock_project)
    changes.write(project, [remove_step_change(project, "clean_parent_w1")])
    project = load_project(mock_project)
    made = stage_script(project, "clean", "python", "raw/parent_w1_export.csv", dataset="parent_w1")
    assert made.path == "scripts/clean_parent_w1.py"
    assert made.step.run == (
        "python scripts/clean_parent_w1.py raw/parent_w1_export.csv data/parent_w1.csv"
    )
    assert made.step.stage == "clean" and made.step.outputs == ["data/parent_w1.csv"]
    assert "with the ID in pid" in made.text and "eps_1_w1" in made.text
    assert "def clean(raw: pd.DataFrame)" in made.text
    change = step_change(project, None, made.step)
    assert changes.check(project, [change]) == []
    extract = stage_script(project, "extract", "r", "derivatives/eeg/ses-1", dataset="eeg_w1")
    assert "data.frame(pid = " in extract.text and extract.step.stage == "extract"
    process = stage_script(
        project, "process", "python", "raw/eeg", "derivatives/eeg", name="process_eeg"
    )
    assert process.step.outputs == ["derivatives/eeg"] and "def process(" in process.text
    with pytest.raises(EditError, match="Choose what"):
        stage_script(project, "clean", "r", "", dataset="parent_w1")
