from labcatalog.project import load_project
from labcatalog.resolve import resolve_catalog


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_every_mapped_item_becomes_a_variable(mock_project):
    catalog = resolve_catalog(load_project(mock_project))
    counts = {
        name: len(catalog.variables_for(name))
        for name in ["parent_w1", "parent_w3", "child_w1", "child_w2", "child_w3"]
    }
    assert counts == {
        "parent_w1": 17,
        "parent_w3": 17,
        "child_w1": 9,
        "child_w2": 12,
        "child_w3": 12,
    }
    variable = next(v for v in catalog.variables if v.column == "ecs_1_w2")
    assert (variable.study, variable.wave, variable.reporter, variable.target) == (
        "mock_study",
        "2",
        "parent",
        "child",
    )
    assert variable.reverse
    assert [o.label for o in variable.response_options] == ["Rarely", "Sometimes", "Usually"]


def test_scores_know_their_columns_and_reverse_bounds(mock_project):
    catalog = resolve_catalog(load_project(mock_project))
    score = next(s for s in catalog.scores_for("child_w1") if s.score_id == "ems_total")
    assert score.columns == [f"ems_{n}_w1" for n in range(1, 10)]
    assert score.reverse_bounds == {
        "ems_1_w1": (0.0, 3.0),
        "ems_4_w1": (0.0, 3.0),
        "ems_9_w1": (0.0, 3.0),
    }
    assert (score.missing_rule, score.min_valid, score.unavailable_items) == ("prorate", 7, [])
    assert len(catalog.scores) == 30


def test_overrides_change_one_wave_only(mock_project):
    edit(
        mock_project / "studies" / "mock_study.yaml",
        "{instrument: example_mood, datasets: [child_w1, child_w2, child_w3], target: self}",
        "{instrument: example_mood, datasets: [child_w1, child_w2, child_w3], target: self, overrides: "
        "[{item: ems_2, dataset: child_w2, text: I felt down.}, {item: ems_6, dataset: child_w2, dropped: true}]}",
    )
    catalog = resolve_catalog(load_project(mock_project))
    texts = {v.column: v.text["default"] for v in catalog.variables if v.item_id == "ems_2"}
    assert texts == {
        "ems_2_w1": "I felt sad.",
        "ems_2_w2": "I felt down.",
        "ems_2_w3": "I felt sad.",
    }
    assert "ems_6_w2" not in {v.column for v in catalog.variables}
    score = next(s for s in catalog.scores_for("child_w2") if s.score_id == "ems_total")
    assert score.unavailable_items == ["ems_6"]


def test_existing_score_column_is_picked_up(mock_project):
    path = mock_project / "maps" / "parent_w1.csv"
    path.write_text(
        path.read_text(encoding="utf-8") + "eps_mean_w1,example_parent_stress,score:eps_mean\n",
        encoding="utf-8",
    )
    catalog = resolve_catalog(load_project(mock_project))
    score = next(s for s in catalog.scores_for("parent_w1") if s.score_id == "eps_mean")
    assert score.existing_column == "eps_mean_w1"
