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
        "maps/child_w3.csv:4",
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


def test_score_fields_belong_on_scores(mock_project):
    path = mock_project / "instruments" / "example_mood.yaml"
    edit(path, "domain: emotion", "domain: emotion\n  topics: [sleep]")
    edit(path, "custom: {topics: [positive affect]}", "custom: {topics: [joy], domain: emotion}")
    messages = sorted(i.message for i in run_validate(mock_project))
    assert messages == [
        "custom.topics: declared for score, not instrument",
        "scores[4] (ems_low_positive).custom.domain: declared for instrument, not score",
        "scores[4] (ems_low_positive).custom.topics: tag(s) not declared: joy",
    ]


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


def test_group_pattern_needs_one_capture(mock_project):
    edit(mock_project / "labcatalog.yaml", r"from_id: '^(\d{4})'", "from_id: '^[0-9]{4}'")
    [issue] = run_validate(mock_project)
    assert issue.message.startswith("ids.group.from_id")


def test_correlate_by_must_name_id_none_or_the_group(mock_project):
    edit(mock_project / "labcatalog.yaml", "correlate_by: family", "correlate_by: household")
    [issue] = run_validate(mock_project)
    assert "family" in issue.message and "household" in issue.message


def test_group_column_needs_a_declared_group(mock_project):
    text = (mock_project / "labcatalog.yaml").read_text(encoding="utf-8")
    start = text.index("  group:")
    end = text.index("stats:")
    text = text[:start] + "\n" + text[end:].replace("correlate_by: family", "correlate_by: id")
    text = text.replace("path: data/child_w2.csv,", "path: data/child_w2.csv, group_column: fam,")
    (mock_project / "labcatalog.yaml").write_text(text, encoding="utf-8")
    [issue] = run_validate(mock_project)
    assert "declare ids.group" in issue.message


def test_scored_items_need_numeric_options(mock_project):
    edit(
        mock_project / "instruments" / "example_mood.yaml",
        "{value: 3, label: Always}",
        "{value: x, label: Always}",
    )
    issues = run_validate(mock_project)
    assert codes(issues) == {"invalid_value"}
    assert "numeric" in issues[0].message


def test_missing_reference_pdf_is_a_warning(mock_project):
    edit(
        mock_project / "instruments" / "example_mood.yaml", "pdf: example_mood.pdf", "pdf: gone.pdf"
    )
    [issue] = run_validate(mock_project)
    assert (issue.code, issue.level) == ("pdf_missing", "warning")
    assert issue.location == "instruments/example_mood.yaml"
    assert "gone.pdf" in issue.message


def test_reference_key_missing_from_the_bib_is_a_warning(mock_project):
    edit(mock_project / "instruments" / "example_mood.yaml", "key: example2019", "key: nobody2020")
    [issue] = run_validate(mock_project)
    assert (issue.code, issue.level) == ("reference_missing", "warning")
    assert issue.location == "instruments/example_mood.yaml"
    assert "nobody2020" in issue.message


def test_study_reference_missing_from_the_bib_is_a_warning(mock_project):
    edit(mock_project / "labcatalog.yaml", "reference: mockstudy2026", "reference: gone2026")
    [issue] = run_validate(mock_project)
    assert (issue.code, issue.level, issue.location) == (
        "reference_missing",
        "warning",
        "labcatalog.yaml",
    )
    assert issue.message.startswith("studies.mock_study.reference:")


def test_missing_bib_is_reported_once(mock_project):
    (mock_project / "references" / "references.bib").unlink()
    [issue] = run_validate(mock_project)
    assert (issue.code, issue.level) == ("bib_missing", "warning")


def test_missing_references_root_is_reported_once(mock_project):
    edit(mock_project / "labcatalog.yaml", "root: references", "root: ~/not-synced-yet")
    [issue] = run_validate(mock_project)
    assert (issue.code, issue.level) == ("references_root_missing", "warning")


def test_item_types(mock_project):
    path = mock_project / "instruments" / "example_demographics.yaml"
    edit(
        path,
        "type: number, min: 3, max: 18}",
        "type: number, min: 18, max: 3, response_set: gender}",
    )
    edit(path, "response_set: education}", "response_set: education, max: 4}")
    edit(
        path,
        "type: text}",
        "type: choice}\nscores:\n  - {id: n, label: N, method: sum, items: [dem_household]}",
    )
    messages = [i.message for i in run_validate(mock_project) if i.code == "invalid_value"]
    assert messages == [
        "items[1] (dem_age).response_set: number items have no response options",
        "items[1] (dem_age): min is above max",
        "items[3] (dem_edu): min and max apply to number items only",
        "items[5] (dem_comment): needs a response_set, or type: number or text",
        "scores[1] (n).items: dem_household is a number item and cannot be scored",
    ]
