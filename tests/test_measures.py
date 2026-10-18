import pytest
import yaml

from labcatalog.gui import analysis as analysis_page
from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project
from labcatalog.reports import measures
from labcatalog.stats import analysis
from labcatalog.stats.cfa import ML, WLSMV, CfaFit


def paragraph(result, omega=None, estimator=WLSMV):
    mood = result.project.instruments["example_mood"]
    fit = CfaFit(
        "example_mood", "child_w1", "total", {}, 100, omega=omega or {}, estimator=estimator
    )
    return measures.paragraph(
        result.project, result.catalog, result.summary, mood, "child_w1", [fit]
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
    text = paragraph(result, {"ems_total": 0.912}, ML)
    assert text.endswith("McDonald's ω was .91.")


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


def test_the_analysis_page_gives_a_paragraph_per_instrument_it_uses(result):
    keys = [
        s.key
        for s in result.catalog.scores
        if (s.instrument_id, s.dataset)
        in {("example_mood", "child_w1"), ("example_parent_stress", "parent_w1")}
    ]
    keys.append(analysis.item_key(analysis.roster_items(result, "child_w1")[0]))
    texts = analysis_page.measure_paragraphs(result, keys)
    # Two mood scores make one paragraph; the roster's columns have none.
    assert len(texts) == 2
    stress, mood = texts
    assert stress.startswith("We used the Example Parenting Stress Scale")
    assert mood.startswith("We used the Example Mood Scale") and "Cronbach's α" in mood
    assert "ω" not in mood
