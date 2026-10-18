import pandas as pd

from labcatalog.pipeline import run_check


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
