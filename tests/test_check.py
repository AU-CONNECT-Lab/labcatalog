import pandas as pd

from labcatalog.ai.cleaning import clean_file_lines
from labcatalog.config import id_pattern
from labcatalog.pipeline import run_catalog, run_check


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def found(report) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for issue in report.issues:
        result.setdefault(issue.code, []).append(issue.message)
    return result


def change_csv(path, change) -> None:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    change(frame)
    frame.to_csv(path, index=False)


def test_mock_reports_only_the_planted_problems(mock_project):
    report = run_check(mock_project)
    errors = {i.code for i in report.issues if i.level == "error"}
    assert errors == {"unexpected_value", "id_whitespace", "id_duplicate"}
    assert any("1021C" in m and "ems_total@child_w1" in m for m in found(report)["same_answer"])


def test_metadata_errors_stop_before_reading_data(mock_project):
    (mock_project / "data" / "child_w1.csv").unlink()
    edit(mock_project / "labcatalog.yaml", "reporters: [parent, child]", "reporters: [parent]")
    assert set(found(run_check(mock_project))) == {"not_in_vocab"}


def test_columns_missing_from_data_and_undescribed_columns(mock_project):
    path = mock_project / "data" / "child_w2.csv"
    frame = pd.read_csv(path, dtype=str, keep_default_na=False).drop(columns=["est_3_w2"])
    frame["notes"] = "x"
    frame.to_csv(path, index=False)
    issues = {i.code: i for i in run_check(mock_project).issues}
    assert issues["column_missing"].location == "maps/child_w2.csv:15"
    assert issues["column_unmapped"].level == "warning"
    assert "notes" in issues["column_unmapped"].message


def test_a_column_another_dataset_of_the_same_file_maps_is_described(mock_project):
    # Each administration of one wide file is a dataset of its own with its own map.
    assert any("notes" in m for m in found(run_check(mock_project))["column_unmapped"])
    line = (
        "  - {name: child_w3, modality: questionnaire, study: mock_study, wave: 3, "
        "reporter: child, source: csv, path: data/child_w3.csv, date_column: visit_date, "
        "snapshot_date: 2026-10-10}\n"
    )
    extra = line.replace("name: child_w3,", "name: child_w3_notes,")
    edit(mock_project / "labcatalog.yaml", line, line + extra)
    (mock_project / "maps" / "child_w3_notes.csv").write_text(
        "column,instrument,item\npid,,\nnotes,,\n", encoding="utf-8"
    )
    report = run_check(mock_project)
    columns = [i for i in report.issues if i.code in ("column_unmapped", "column_missing")]
    assert not any(i.details.get("dataset") in ("child_w3", "child_w3_notes") for i in columns)


def test_duplicate_and_malformed_ids(mock_project):
    def change(frame):
        frame.loc[1, "pid"] = frame.loc[0, "pid"]
        frame.loc[2, "pid"] = "P1003"

    change_csv(mock_project / "data" / "child_w2.csv", change)
    codes = found(run_check(mock_project))
    # P1003 has no family: the roster does not list it.
    assert {"id_duplicate", "id_pattern", "id_not_in_roster"} <= set(codes)


def test_people_on_the_exclusion_list_are_reported_not_removed(mock_project):
    (mock_project / "withdrawn.csv").write_text("id,reason\n1032P,withdrew\n1003,family withdrew\n")
    edit(
        mock_project / "labcatalog.yaml",
        "    reference: mockstudy2026\n",
        "    reference: mockstudy2026\n    exclusions: withdrawn.csv\n",
    )
    messages = found(run_check(mock_project))["excluded_present"]
    # 1032P is in all three parent waves; family 1003 has a parent and a child in all three,
    # a parent's checklist on the child in all three, and the child's files from seven other
    # modalities.
    assert len(messages) == 19
    assert any("1032P" in m and "1003P" in m for m in messages)


def test_possible_identifiers(mock_project):
    def change(frame):
        frame["email"] = ""
        frame.loc[0, "email"] = "parent@example.org"

    change_csv(mock_project / "data" / "parent_w2.csv", change)
    path = mock_project / "maps" / "parent_w2.csv"
    path.write_text(path.read_text(encoding="utf-8") + "email,,\n", encoding="utf-8")
    [message] = found(run_check(mock_project))["possible_identifier"]
    assert "its name and values that look like email addresses" in message


def test_existing_score_column_is_cross_checked(mock_project):
    def change(frame):
        frame["ems_total_w2"] = ""
        frame.loc[0, "ems_total_w2"] = "99"

    change_csv(mock_project / "data" / "child_w2.csv", change)
    path = mock_project / "maps" / "child_w2.csv"
    path.write_text(
        path.read_text(encoding="utf-8") + "ems_total_w2,example_mood,score:ems_total\n",
        encoding="utf-8",
    )
    codes = found(run_check(mock_project))
    assert "1 row(s) differ" in codes["score_mismatch"][0]
    assert "score_coverage" in codes


def test_numbers_outside_their_range(mock_project):
    messages = found(run_check(mock_project))["unexpected_value"]
    [age] = [m for m in messages if m.startswith("dem_age_w2")]
    assert "neither numbers from 3 to 18 nor missing codes: 45" in age


def test_free_text_answers_are_searched_for_identifiers(mock_project):
    def change(frame):
        frame.loc[0, "dem_comment_w1"] = "Call me at 334-555-0100"

    change_csv(mock_project / "data" / "parent_w1.csv", change)
    [message] = found(run_check(mock_project))["possible_identifier"]
    assert message.startswith("dem_comment_w1") and "phone numbers" in message


def pattern_issues(root) -> dict[str, str]:
    # By dataset, since the pilot reads child_w1's file; a roster by its path.
    return {
        i.details.get("dataset", i.location.split(":")[0]): i.message
        for i in run_check(root).issues
        if i.code == "id_pattern"
    }


def test_a_study_can_write_its_ids_its_own_way(pilot_project):
    config = pilot_project / "labcatalog.yaml"
    edit(config, "  pilot:\n", "  pilot:\n    id_pattern: '^P-\\d{4}$'\n")
    found = pattern_issues(pilot_project)
    # Only the pilot's files and roster are held to its own pattern.
    assert all("studies.pilot.id_pattern" in m for m in found.values())
    assert set(found) == {"pilot_w1", "data/pilot_roster.csv"}
    edit(config, "pattern: '^\\d{4}[PC]$'", "pattern: '^X$'")
    edit(config, "id_pattern: '^P-\\d{4}$'", "id_pattern: '^\\d{4}[PC]$'")
    found = pattern_issues(pilot_project)
    assert "pilot_w1" not in found and "data/pilot_roster.csv" not in found
    assert "ids.pattern" in found["child_w1"]
    result = run_catalog(pilot_project)
    assert id_pattern(result.project.config, "pilot") == (
        "^\\d{4}[PC]$",
        "studies.pilot.id_pattern",
    )
    lines = clean_file_lines(result.project, result.catalog, "pilot_w1")
    assert any("IDs match the regular expression ^\\d{4}[PC]$; keep rows" in line for line in lines)


def test_a_studys_pattern_must_be_a_regular_expression(pilot_project):
    edit(pilot_project / "labcatalog.yaml", "  pilot:\n", "  pilot:\n    id_pattern: '^(\\d'\n")
    messages = found(run_check(pilot_project))["invalid_value"]
    assert any(m.startswith("studies.pilot.id_pattern: invalid pattern") for m in messages)
