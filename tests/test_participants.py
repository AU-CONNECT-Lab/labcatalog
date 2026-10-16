import yaml

from labcatalog import participants
from labcatalog.gui import methods
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project
from labcatalog.validate import validate_project


def test_default_paragraph_gives_waves_counts_and_retention(mock_project):
    result = run_catalog(mock_project)
    text = participants.paragraph(result.project, result.summary, "mock_study")
    assert text.startswith(
        "Data were collected in three waves: Wave 1 (2024-03-01 to 2024-10-31), Wave 2"
    )
    assert "Wave 3 (since 2026-03-01)." in text
    assert "At Wave 1, 191 parent and 182 child respondents from 191 family groups" in text
    assert "At Wave 2, 155 of 191 parent respondents (81%) and 143 of 182 child" in text
    assert text.endswith("12 parent and 15 child respondents were new.")


def test_study_template_wins_over_the_project_one(mock_project):
    config = mock_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["participants"] = "{study}: {n_waves} waves. {retention}"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = run_catalog(mock_project)
    text = participants.paragraph(result.project, result.summary, "mock_study")
    assert text.startswith("Mock Family Study: three waves. At Wave 2,")
    content = next(iter(result.project.studies.values()))
    content.participants = "{counts}"
    assert participants.template_for(result.project, "mock_study") == "{counts}"


def test_unknown_participants_placeholder_is_an_error(mock_project):
    config = mock_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["participants"] = "{name} took part."
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    issues = validate_project(load_project(mock_project))
    found = [i for i in issues if i.message.startswith("participants:")]
    assert len(found) == 1 and "unknown placeholder {name}" in found[0].message


def test_retention_table_shows_who_came_back(mock_project):
    result = run_catalog(mock_project)
    columns, rows = methods.retention_table(result, "mock_study")
    labels = [c["label"] for c in columns]
    assert labels[:4] == ["Wave", "Dates", "Parent n", "Parent returning"]
    assert labels[-2:] == ["Family groups", "With every reporter"]
    assert (rows[0]["n_parent"], rows[0]["back_parent"]) == (191, "")
    assert rows[1]["back_parent"] == "155 (81%)"
