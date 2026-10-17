import pytest

from labcatalog.charts import mindmap
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing
from labcatalog.project import load_project


def branches(option):
    return option["series"][0]["data"][0]["children"]


def test_a_total_of_the_subscales_is_one_leaf_and_the_subscales_hold_their_items(mock_project):
    mood = load_project(mock_project).instruments["example_mood"]
    found = branches(mindmap.instrument_tree(mood))
    assert [b["name"] for b in found] == [
        "Total score (sum of 9)",
        "Sadness (sum)",
        "Worry and fatigue (sum)",
        "Low positive affect (sum)",
        "Answer options",
    ]
    assert "children" not in found[0]
    assert [c["name"] for c in found[3]["children"]][0] == "ems_1  I felt happy. (R)"
    assert found[-1]["collapsed"] and found[-1]["children"][0]["name"] == "frequency"
    # A row each for the total, the nine items and the collapsed answer options.
    assert mindmap.tree_height(mindmap.instrument_tree(mood)) == 11 * mindmap.ROW_HEIGHT


def test_items_without_scores_hang_from_the_instrument(mock_project):
    project = load_project(mock_project)
    found = branches(mindmap.instrument_tree(project.instruments["example_demographics"]))
    assert found[0]["name"] == "dem_age  Child age"
    assert mindmap.UNSCORED not in [b["name"] for b in found]


def test_items_left_out_of_every_score_get_their_own_branch(mock_project):
    mood = load_project(mock_project).instruments["example_mood"]
    mood.scores = [s for s in mood.scores if s.id == "ems_sadness"]
    found = branches(mindmap.instrument_tree(mood))
    assert [b["name"] for b in found] == ["Sadness (sum)", mindmap.UNSCORED, "Answer options"]
    assert len(found[1]["children"]) == 6


def test_the_edited_text_is_read_or_its_first_problem_told():
    instrument = editing.instrument_from_text("id: a\nname: A\nitems: [{id: a_1, text: One}]\n")
    assert [i.id for i in instrument.items] == ["a_1"]
    with pytest.raises(EditError, match="Not valid YAML yet"):
        editing.instrument_from_text("id: a\nname: [\n")
    with pytest.raises(EditError, match="^name: Field required"):
        editing.instrument_from_text("id: a\n")
    assert editing.is_instrument_file("drafts/a.yaml")
    assert not editing.is_instrument_file("studies/a.yaml")
