import shutil
from pathlib import Path

import pytest

from labcatalog.exceptions import MetadataError, ProjectNotFoundError
from labcatalog.project import load_project


def load_issues(root: Path) -> list:
    with pytest.raises(MetadataError) as caught:
        load_project(root)
    return caught.value.issues


def test_loads_demo_project(demo_project):
    project = load_project(demo_project)
    assert project.config.project.name == "Demo Catalog"
    assert list(project.instruments) == ["example_mood"]
    assert list(project.studies) == ["demo_study"]
    assert list(project.config.studies["demo_study"].waves) == ["1"]


def test_folder_without_config_is_not_a_project(tmp_path):
    with pytest.raises(ProjectNotFoundError):
        load_project(tmp_path)


def test_misspelled_key_is_reported_with_one_based_item_position(demo_project):
    path = demo_project / "instruments" / "example_mood.yaml"
    path.write_text(path.read_text().replace("I had trouble sleeping.}", "x, revrse: true}"))
    [issue] = load_issues(demo_project)
    assert issue.code == "extra_forbidden"
    assert issue.location == "instruments/example_mood.yaml"
    assert issue.message.startswith("items[3].revrse:")


def test_problems_from_all_files_are_collected(demo_project):
    config = demo_project / "labcatalog.yaml"
    config.write_text(config.read_text().replace("project:", "projct:"))
    study = demo_project / "studies" / "demo_study.yaml"
    study.write_text(study.read_text().replace("[parent_w1]", "[parent_w1"))
    issues = load_issues(demo_project)
    assert {issue.code for issue in issues} == {"missing", "extra_forbidden", "yaml_syntax"}
    assert any(issue.location.startswith("studies/demo_study.yaml:") for issue in issues)


def test_duplicate_instrument_id_is_reported(demo_project):
    instruments = demo_project / "instruments"
    shutil.copy(instruments / "example_mood.yaml", instruments / "copy.yml")
    [issue] = load_issues(demo_project)
    assert issue.code == "duplicate_id"
    assert issue.location == "instruments/example_mood.yaml"
    assert "instruments/copy.yml" in issue.message


def test_empty_file_reports_required_fields(demo_project):
    (demo_project / "studies" / "demo_study.yaml").write_text("")
    [issue] = load_issues(demo_project)
    assert issue.code == "missing"
    assert issue.message.startswith("study:")
