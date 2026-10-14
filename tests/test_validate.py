from pathlib import Path

from labcatalog.issues import has_errors
from labcatalog.pipeline import run_validate


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_mock_project_is_clean(mock_project):
    assert run_validate(mock_project) == []


def test_unknown_instrument_in_study(mock_project):
    edit(
        mock_project / "studies" / "mock_study.yaml",
        "instrument: example_mood,",
        "instrument: example_moood,",
    )
    issues = run_validate(mock_project)
    assert codes(issues) == {"unknown_reference"}
    assert [i.location for i in issues] == [
        "studies/mock_study.yaml",
        "maps/child_w1.csv:4",
        "maps/child_w2.csv:4",
    ]
    assert "example_moood" in issues[0].message


def test_reporter_outside_vocab(mock_project):
    edit(mock_project / "labcatalog.yaml", "reporters: [parent, child]", "reporters: [parent]")
    issues = run_validate(mock_project)
    assert codes(issues) == {"not_in_vocab"}
    assert all("reporter" in issue.message for issue in issues)


def test_missing_code_that_is_also_a_response_option(mock_project):
    edit(
        mock_project / "labcatalog.yaml",
        "{code: -98, label: not applicable}",
        "{code: 3, label: not applicable}",
    )
    issues = run_validate(mock_project)
    assert codes(issues) == {"missing_code_collision"}
    assert any(issue.location == "instruments/example_mood.yaml" for issue in issues)


def test_map_row_with_unknown_item_points_to_the_line(mock_project):
    edit(
        mock_project / "maps" / "parent_w1.csv",
        "eps_2_w1,example_parent_stress,eps_2",
        "eps_2_w1,example_parent_stress,eps_22",
    )
    issues = run_validate(mock_project)
    assert any(
        i.code == "unknown_reference" and i.location == "maps/parent_w1.csv:5" for i in issues
    )


def test_unmapped_item_is_only_a_warning(mock_project):
    edit(mock_project / "maps" / "child_w1.csv", "ems_6_w1,example_mood,ems_6\n", "")
    issues = run_validate(mock_project)
    assert codes(issues) == {"unmapped_item"}
    assert not has_errors(issues)


def test_missing_map_file(mock_project):
    (mock_project / "maps" / "child_w2.csv").unlink()
    [issue] = run_validate(mock_project)
    assert issue.code == "map_missing"


def test_map_saved_in_a_legacy_excel_encoding(mock_project):
    (mock_project / "maps" / "child_w2.csv").write_bytes(
        "column,instrument,item\ncaf\xe9,,\n".encode("cp1252")
    )
    [issue] = run_validate(mock_project)
    assert issue.code == "map_encoding"


def test_custom_fields_must_be_declared_and_valid(mock_project):
    edit(
        mock_project / "instruments" / "example_mood.yaml",
        "domain: emotion",
        "domain: mood\n  topic: x",
    )
    issues = run_validate(mock_project)
    assert codes(issues) == {"invalid_value", "undeclared_custom_field"}


def test_tags_field(mock_project):
    edit(
        mock_project / "labcatalog.yaml",
        "custom_fields:\n",
        "custom_fields:\n  - {name: tags, applies_to: instrument, type: tags, choices: [short, self-report]}\n",
    )
    edit(
        mock_project / "instruments" / "example_mood.yaml",
        "domain: emotion",
        "domain: emotion\n  tags: [short, brief]",
    )
    [issue] = run_validate(mock_project)
    assert issue.code == "invalid_value"
    assert "brief" in issue.message


def test_demographics_are_never_imputed(mock_project):
    path = mock_project / "instruments" / "example_mood.yaml"
    edit(path, "construct_name:", "kind: demographics\nconstruct_name:")
    [issue] = run_validate(mock_project)
    assert issue.code == "invalid_value"
    assert "never imputed" in issue.message


def test_min_valid_without_prorating_warns(mock_project):
    edit(mock_project / "instruments" / "example_mood.yaml", "missing_rule: prorate, ", "")
    [issue] = run_validate(mock_project)
    assert issue.level == "warning"


def test_blank_rows_left_by_excel_are_ignored(mock_project):
    path = mock_project / "maps" / "child_w2.csv"
    path.write_text(path.read_text(encoding="utf-8") + ",,\n,,\n", encoding="utf-8")
    assert run_validate(mock_project) == []
