from labcatalog.metadata import editing, fields, forms
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project

TOPICS = "  - name: topics\n    label: Topics"


def test_a_field_renamed_in_place_or_gone_is_found():
    old = "custom_fields:\n  - {name: a}\n  - {name: b}\n"
    assert fields.field_changes(old, old.replace("name: b", "name: c")) == ({"b": "c"}, [])
    assert fields.field_changes(old, "custom_fields:\n  - {name: a}\n") == ({}, ["b"])
    assert fields.field_changes(old, old) == ({}, [])


def test_renaming_a_field_renames_its_values_and_filters_in_every_file(mock_project):
    config = mock_project / "labcatalog.yaml"
    old = config.read_text(encoding="utf-8")
    new = old.replace(TOPICS, "  - name: themes\n    label: Themes")
    renames, removed = fields.field_changes(old, new)
    assert renames == {"topics": "themes"}
    assert fields.field_uses(mock_project, ["topics"])["topics"] > 0
    changed = fields.changed_values(new, renames, removed)
    assert (
        "facets: [study, wave, coverage, reporter, target, modality, domain, themes, status]"
        in changed
    )
    config.write_text(changed, encoding="utf-8")
    saved = fields.apply_elsewhere(mock_project, renames, removed)
    assert "instruments/example_parent_stress.yaml" in saved
    assert "topics:" not in (mock_project / "instruments/example_parent_stress.yaml").read_text(
        encoding="utf-8"
    )
    errors = [i for i in validate_project(load_project(mock_project)) if i.level == "error"]
    assert not errors


def test_deleting_a_field_removes_its_values(mock_project):
    config = mock_project / "labcatalog.yaml"
    old = config.read_text(encoding="utf-8")
    start = old.index(TOPICS)
    end = old.index("\n\n", start)
    new = old[:start] + old[end + 1 :]
    renames, removed = fields.field_changes(old, new)
    assert removed == ["topics"]
    config.write_text(fields.changed_values(new, renames, removed) or new, encoding="utf-8")
    fields.apply_elsewhere(mock_project, renames, removed)
    assert fields.field_uses(mock_project, ["topics"]) == {"topics": 0}
    assert not [i for i in validate_project(load_project(mock_project)) if i.level == "error"]


def test_a_dataset_field_sits_on_each_datasets_line_and_takes_new_values(mock_project):
    config = mock_project / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8").replace(
        "custom_fields:\n",
        "custom_fields:\n  - {name: site, applies_to: dataset, type: choice, choices: [Auburn]}\n",
        1,
    )
    config.write_text(text, encoding="utf-8")
    found = {s.key: s for s in forms.sections(mock_project, "labcatalog.yaml", text)}
    assert list(found) == ["custom_fields", "datasets"]
    assert "custom:site" in found["datasets"].primary
    typed = text.replace(
        "snapshot_date: 2026-10-10}", "snapshot_date: 2026-10-10, custom: {site: Emory}}", 1
    )
    assert editing.new_tags(mock_project, typed) == {"site": ["Emory"]}


def test_an_option_renamed_in_place_is_found_and_a_removed_one_is_not():
    old = "custom_fields:\n  - {name: site, choices: [Auburn, Opelika]}\n"
    assert fields.option_changes(old, old.replace("Opelika", "Lee"), {}) == {
        "site": {"Opelika": "Lee"}
    }
    renamed = old.replace("site", "place").replace("Auburn", "AU")
    assert fields.option_changes(old, renamed, {"site": "place"}) == {"place": {"Auburn": "AU"}}
    assert fields.option_changes(old, old.replace(", Opelika", ""), {}) == {}


def test_renaming_an_option_renames_it_in_tags_and_choices_in_every_file(mock_project):
    config = mock_project / "labcatalog.yaml"
    old = config.read_text(encoding="utf-8")
    new = old.replace("parenting, sleep]", "parenting, sleep and settling]")
    renames, removed = fields.field_changes(old, new)
    options = fields.option_changes(old, new, renames)
    assert options == {"topics": {"sleep": "sleep and settling"}}
    assert fields.option_uses(mock_project, options, renames)["topics", "sleep"] > 0
    config.write_text(
        fields.changed_values(new, renames, removed, options) or new, encoding="utf-8"
    )
    saved = fields.apply_elsewhere(mock_project, renames, removed, options)
    assert "instruments/example_child_sleep.yaml" in saved
    sleep = (mock_project / "instruments/example_child_sleep.yaml").read_text(encoding="utf-8")
    assert "topics: [sleep and settling]" in sleep and "topics: [sleep]" not in sleep
    assert fields.option_uses(mock_project, options, renames)["topics", "sleep"] == 0
    assert not [i for i in validate_project(load_project(mock_project)) if i.level == "error"]
