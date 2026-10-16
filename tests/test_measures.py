import pytest
import yaml

from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project
from labcatalog.reports import measures


def paragraph(result, omega=None):
    mood = result.project.instruments["example_mood"]
    return measures.paragraph(
        result.project, result.catalog, result.summary, mood, "child_w1", omega or {}
    )


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def test_default_paragraph_reads_like_a_measures_section(result):
    text = paragraph(result, {"ems_sadness": 0.834, "ems_total": 0.912})
    assert text.startswith(
        "We used the Example Mood Scale (EMS; Example & Sample, 2019). It asks how often"
    )
    assert "The EMS has nine items, each answered from 0 (Never) to 3 (Always)." in text
    assert "Items 1, 4, and 9 are reverse-scored." in text
    assert (
        "Scores are the sum of the items for Total score (nine items), Sadness (three items)"
        in text
    )
    assert "Cronbach's α was ." in text and " for Low positive affect." in text
    assert text.endswith("Categorical ω was .91 for Total score and .83 for Sadness.")


def test_instrument_template_wins_over_the_project_one(mock_project):
    config = mock_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["measures"] = "{name} by {reporter}."
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = run_catalog(mock_project)
    assert paragraph(result) == "Example Mood Scale by child."
    sleep = result.project.instruments["example_child_sleep"]
    sleep.measures = "{abbreviation}: {n_items} items{{1}}."
    assert measures.template_for(result.project, sleep) == sleep.measures


def test_unknown_placeholders_and_stray_braces_are_errors(mock_project):
    path = mock_project / "instruments" / "example_mood.yaml"
    path.write_text(
        path.read_text(encoding="utf-8") + "measures: We used {nmae}.\n", encoding="utf-8"
    )
    issues = validate_project(load_project(mock_project))
    found = [i for i in issues if i.message.startswith("measures:")]
    assert len(found) == 1 and "unknown placeholder {nmae}" in found[0].message
    assert measures.placeholder_problem("{name", measures.PLACEHOLDERS) is not None
    assert measures.placeholder_problem("a {{literal}} {name}", measures.PLACEHOLDERS) is None
