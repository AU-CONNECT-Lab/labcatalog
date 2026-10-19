import yaml

from labcatalog.metadata import changes
from labcatalog.metadata.templates import template_change
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project
from labcatalog.reports import template_examples, templates


def test_a_project_template_is_written_under_templates_and_the_default_removes_it(mock_project):
    project = load_project(mock_project)
    change = template_change(project, "measures", {"paragraph": "We gave {named}. {alpha}"})
    assert "\ntemplates:\n  measures: |\n    We gave {named}. {alpha}\n" in change.text
    changes.write(project, [change])
    project = load_project(mock_project)
    assert templates.project_text(project.config, "measures") == "We gave {named}. {alpha}"
    default = templates.TEMPLATES["measures"].slot("paragraph").default
    change = template_change(project, "measures", {"paragraph": f"  {default}\n"})
    assert "templates" not in change.text


def test_a_study_and_an_instrument_keep_their_own_wording_unless_it_is_the_projects(mock_project):
    project = load_project(mock_project)
    change = template_change(project, "participants", {"paragraph": "{counts}"}, "mock_study")
    assert change.path == "studies/mock_study.yaml"
    assert "\nparticipants: |\n  {counts}\nadministrations:" in change.text
    change = template_change(project, "measures", {"paragraph": "{name}."}, "example_mood")
    data = yaml.safe_load(change.text)
    assert data["measures"] == "{name}.\n"
    assert list(data).index("measures") == list(data).index("description") + 1
    project_wording = templates.project_text(project.config, "participants")
    change = template_change(project, "participants", {"paragraph": project_wording}, "mock_study")
    assert change.text == change.opened.text


def test_a_template_in_parts_keeps_only_the_parts_that_differ(mock_project):
    project = load_project(mock_project)
    found = templates.TEMPLATES["regression"]
    texts = {s.key: s.default for s in found.slots} | {"intro": "Simple regressions:"}
    change = template_change(project, "regression", texts)
    assert "\ntemplates:\n  regression:\n    intro: |\n      Simple regressions:\n" in change.text
    assert "predictor" not in change.text.split("templates:")[1]


def test_unknown_templates_and_parts_are_errors(mock_project):
    config = mock_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["templates"] = {
        "discussion": "x",
        "measures": {"paragraph": "x"},
        "regression": {"outro": "x", "intro": "{nope}"},
    }
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    messages = [i.message for i in validate_project(load_project(mock_project))]
    assert any(m.startswith("templates: unknown template discussion") for m in messages)
    assert "templates: measures is one text" in messages
    assert any(m.startswith("templates: regression has no part outro") for m in messages)
    data["templates"] = {"regression": {"intro": "{nope}"}}
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    messages = [i.message for i in validate_project(load_project(mock_project))]
    assert any(m.startswith("regression.intro: unknown placeholder {nope}") for m in messages)


def test_each_built_in_part_uses_its_placeholders_and_its_example_fills_it():
    for found in templates.TEMPLATES.values():
        for slot in found.slots:
            assert templates.placeholder_problem(slot.default, slot.placeholders) is None
            if found.part == templates.RESULTS:
                assert set(slot.example) == set(slot.placeholders), (found.key, slot.key)


def test_each_results_template_has_an_example_written_with_the_wording_being_edited():
    results_keys = [k for k, t in templates.TEMPLATES.items() if t.part == templates.RESULTS]
    assert sorted(template_examples.EXAMPLES) == sorted(results_keys)
    for key, write in template_examples.EXAMPLES.items():
        assert write(templates.Wording())
    edited = templates.Wording({"groups": {"two": "{outcome} differed ({p})."}})
    assert template_examples.groups(edited) == "Mood differed (p = .023)."
