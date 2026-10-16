import difflib

import pytest

from labcatalog.exceptions import EditError
from labcatalog.metadata import editing, records

MOOD = "instruments/example_mood.yaml"
STUDY = "studies/mock_study.yaml"


def changes(before: str, after: str) -> list[str]:
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line for line in lines if line[:1] in "+-" and line[:3] not in ("+++", "---")]


def test_tables_belong_to_their_files():
    assert list(records.tables_for(MOOD)) == ["items", "scores", "response_sets"]
    assert list(records.tables_for("labcatalog.yaml")) == ["datasets"]
    assert list(records.tables_for(STUDY)) == ["administrations", "overrides"]
    assert records.tables_for("maps/child_w1.csv") == {}


def test_only_changed_cells_change(mock_project):
    text = editing.open_file(mock_project, MOOD).text
    rows = records.read_rows(text, "items", records.ITEMS)
    assert rows[0] | {records.ORIGIN: 0} == rows[0]
    assert (rows[0]["reverse"], rows[0]["type"], rows[0]["subscales"]) == (True, "choice", "")
    rows[0]["reverse"] = False
    rows[1]["text"] = "I felt very sad."
    del rows[8]
    rows.append({"id": "ems_10", "text": "I slept badly.", "type": "choice", "reverse": False})
    assert changes(text, records.write_rows(text, "items", records.ITEMS, rows)) == [
        "-  - {id: ems_1, text: I felt happy., reverse: true}",
        "-  - {id: ems_2, text: I felt sad.}",
        "+  - {id: ems_1, text: I felt happy.}",
        "+  - {id: ems_2, text: I felt very sad.}",
        "-  - {id: ems_9, text: I had fun with my friends., reverse: true}",
        "+  - {id: ems_10, text: I slept badly.}",
    ]
    scores = records.read_rows(text, "scores", records.SCORES)
    scores[1]["items"] = "ems_2, ems_6"
    [old, new] = changes(text, records.write_rows(text, "scores", records.SCORES, scores))
    assert old.replace("ems_6, ems_7]", "ems_6]") == "-" + new[1:]
    assert "custom: {topics: [negative affect]}" in new


def test_rows_go_into_an_empty_list_one_per_line(mock_project):
    path = editing.new_instrument(mock_project, "new_scale")
    text = editing.open_file(mock_project, path).text
    rows = [{"id": "n_1", "text": "One"}, {"id": "n_2", "text": "Two", "min": "1", "max": 5.5}]
    written = records.write_rows(text, "items", records.ITEMS, rows)
    assert (
        "items:\n  - {id: n_1, text: One}\n  - {id: n_2, text: Two, min: 1, max: 5.5}\n" in written
    )
    assert editing.check_text(path, written) == []


def test_options_are_grouped_into_their_sets(mock_project):
    often = "      - {value: 2, label: Often}\n"
    text = editing.open_file(mock_project, MOOD).text.replace(often, "      # middle\n" + often)
    rows = records.read_rows(text, "response_sets", records.OPTIONS)
    assert rows[1] == {
        records.ORIGIN: [0, 1],
        "id": "frequency",
        "value": "1",
        "label": "Sometimes",
    }
    rows[0]["label"] = "Not at all"
    del rows[3]
    rows.append({"id": "yes_no", "value": "1", "label": "Yes"})
    rows.append({"id": "yes_no", "value": "0", "label": "No"})
    rows.insert(1, {"id": "frequency", "value": "0.5", "label": "Rarely"})
    written = records.write_rows(text, "response_sets", records.OPTIONS, rows)
    assert changes(text, written) == [
        "-      - {value: 0, label: Never}",
        "+      - {value: 0, label: Not at all}",
        "+      - {value: 0.5, label: Rarely}",
        "-      - {value: 3, label: Always}",
        "+  - id: yes_no",
        "+    options:",
        "+      - {value: 1, label: 'Yes'}",
        "+      - {value: 0, label: 'No'}",
    ]
    assert "# middle" in written
    assert editing.check_text(MOOD, written) == []


def test_renaming_a_set_or_moving_one_option(mock_project):
    text = editing.open_file(mock_project, MOOD).text
    rows = records.read_rows(text, "response_sets", records.OPTIONS)
    for row in rows:
        row["id"] = "often"
    assert changes(text, records.write_rows(text, "response_sets", records.OPTIONS, rows)) == [
        "-  - id: frequency",
        "+  - id: often",
    ]
    rows = records.read_rows(text, "response_sets", records.OPTIONS)
    rows[3]["id"] = "label"
    rows[3]["value"] = "x"
    assert changes(text, records.write_rows(text, "response_sets", records.OPTIONS, rows)) == [
        "-      - {value: 3, label: Always}",
        "+  - id: label",
        "+    options:",
        "+      - {value: x, label: Always}",
    ]


def test_administrations_keep_their_overrides(mock_project):
    dropped = "overrides: [{item: ecs_1, dropped: true}]"
    text = editing.open_file(mock_project, STUDY).text.replace(
        "target: child}", f"target: child, {dropped}}}"
    )
    rows = records.read_rows(text, "administrations", records.ADMINISTRATIONS)
    assert rows[1]["datasets"] == "parent_w1, parent_w2, parent_w3"
    rows[1]["reversed_in_data"] = True
    rows[1]["datasets"] = "parent_w1, parent_w2"
    rows[4]["target"] = "self"
    written = records.write_rows(text, "administrations", records.ADMINISTRATIONS, rows)
    [_, sleep, _, demographics] = changes(text, written)
    assert sleep.endswith(
        f"datasets: [parent_w1, parent_w2], target: child, {dropped}, reversed_in_data: true}}"
    )
    assert demographics.endswith("datasets: [parent_w1, parent_w2, parent_w3], target: self}")
    assert editing.check_text(STUDY, written) == []


def test_bad_cells_and_per_language_text_are_reported():
    with pytest.raises(EditError, match="Min: 'a lot' is not a number"):
        records.write_rows("items: []\n", "items", records.ITEMS, [{"id": "x", "min": "a lot"}])
    with pytest.raises(EditError, match="Set: every row needs one"):
        records.write_rows("x: 1\n", "response_sets", records.OPTIONS, [{"value": "1"}])
    with pytest.raises(EditError, match="empty has no options"):
        text = "response_sets:\n  - {id: empty, options: []}\n"
        records.read_rows(text, "response_sets", records.OPTIONS)
    with pytest.raises(EditError, match="not valid YAML"):
        records.read_rows("items:\n  - {id: x\n", "items", records.ITEMS)
    with pytest.raises(EditError, match="per language"):
        records.read_rows("items:\n  - {id: x, text: {en: Hi, es: Hola}}\n", "items", records.ITEMS)


def test_custom_fields_get_columns_and_a_table_of_their_own(mock_project):
    fields = editing.custom_fields(mock_project)
    tables = records.tables_for(MOOD, fields)
    assert list(tables) == ["items", "scores", "response_sets", "custom"]
    assert tables["scores"].columns[-1].key == "custom:topics"
    assert "custom:topics" not in [c.key for c in records.tables_for(MOOD)["scores"].columns]
    text = editing.open_file(mock_project, MOOD).text
    scores = records.read_rows(text, "scores", tables["scores"])
    assert [row["custom:topics"] for row in scores][2:] == [
        "negative affect, sleep",
        "positive affect",
    ]
    scores[1]["custom:topics"] = "sleep, parenting"
    scores[3]["custom:topics"] = ""
    written = records.write_rows(text, "scores", tables["scores"], scores)
    sadness = "  - {id: ems_sadness, label: Sadness, method: sum, items: [ems_2, ems_6, ems_7], "
    low = "  - {id: ems_low_positive, label: Low positive affect, method: sum, items: [ems_1, ems_4, ems_9]"
    assert changes(text, written) == [
        f"-{sadness}custom: {{topics: [negative affect]}}}}",
        f"+{sadness}custom: {{topics: [sleep, parenting]}}}}",
        f"-{low}, custom: {{topics: [positive affect]}}}}",
        f"+{low}}}",
    ]
    assert editing.check_text(MOOD, written) == []
    scores[1]["custom:topics"] = "sleep, naps"
    with pytest.raises(EditError, match="Topics: naps not declared"):
        records.write_rows(text, "scores", tables["scores"], scores)
    [row] = records.read_rows(text, "custom", tables["custom"])
    assert row["custom:domain"] == "emotion"
    row["custom:domain"] = ""
    cleared = records.write_rows(text, "custom", tables["custom"], [row])
    assert changes(text, cleared) == ["-custom:", "-  domain: emotion"]


def test_a_date_field_is_written_as_a_date(mock_project):
    config = mock_project / "labcatalog.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "custom_fields:\n",
            "custom_fields:\n  - {name: approved, applies_to: dataset, type: date}\n",
        ),
        encoding="utf-8",
    )
    table = records.tables_for("labcatalog.yaml", editing.custom_fields(mock_project))["datasets"]
    text = editing.open_file(mock_project, "labcatalog.yaml").text
    rows = records.read_rows(text, "datasets", table)
    rows[0]["custom:approved"] = "2026-01-31"
    written = records.write_rows(text, "datasets", table, rows)
    assert "custom: {approved: 2026-01-31}" in written
    assert editing.check_text("labcatalog.yaml", written) == []
    rows[0]["custom:approved"] = "Jan 31"
    with pytest.raises(EditError, match="not a date"):
        records.write_rows(text, "datasets", table, rows)


def test_overrides_point_to_their_administration(mock_project):
    text = editing.open_file(mock_project, STUDY).text
    table = records.with_entries(records.OVERRIDES, text)
    assert table.columns[0].choices[:2] == ("1: example_parent_stress", "2: example_child_sleep")
    assert records.read_rows(text, "overrides", table) == []
    row = {"administration": "2: example_child_sleep", "item": "ecs_1", "dropped": True}
    written = records.write_rows(text, "overrides", table, [row])
    [line] = changes(text, written)[1:]
    assert line.endswith("target: child, overrides: [{item: ecs_1, dropped: true}]}")
    assert editing.check_text(STUDY, written) == []
    [moved] = records.read_rows(written, "overrides", table)
    moved["administration"] = "3: example_mood"
    again = records.write_rows(written, "overrides", table, [moved])
    [line] = changes(text, again)[1:]
    assert line.startswith("+  - {instrument: example_mood,")
    assert line.endswith("target: self, overrides: [{item: ecs_1, dropped: true}]}")
    assert records.write_rows(again, "overrides", table, []) == text
    with pytest.raises(EditError, match="Administration: choose one"):
        records.write_rows(text, "overrides", table, [{"item": "ecs_1"}])


def test_dragged_rows_move_their_entries(mock_project):
    text = editing.open_file(mock_project, MOOD).text
    rows = records.read_rows(text, "items", records.ITEMS)
    rows.insert(0, rows.pop(8))
    written = records.write_rows(text, "items", records.ITEMS, rows)
    ids = [line.split(",")[0] for line in written.splitlines() if line.startswith("  - {id: ems_")]
    assert ids[:2] == ["  - {id: ems_9", "  - {id: ems_1"] and len(ids) == 9
    assert editing.check_text(MOOD, written) == []
