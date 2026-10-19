import pytest
import yaml

from labcatalog.config import PrepareStep
from labcatalog.exceptions import EditError
from labcatalog.metadata import changes
from labcatalog.metadata.scripts import (
    new_script,
    project_scripts,
    remove_step_change,
    script_of,
    step_change,
)
from labcatalog.project import load_project


def test_scripts_are_listed_with_the_steps_that_run_them(mock_project):
    (mock_project / "scripts" / "draft.R").write_text("x <- 1\n", encoding="utf-8")
    (mock_project / "scripts" / "notes.txt").write_text("not a script\n", encoding="utf-8")
    found = project_scripts(load_project(mock_project))
    by_path = {s.path: s for s in found.steps}
    assert len(by_path["scripts/clean_export.py"].steps) == 9
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
