import difflib

import pytest

from labcatalog import editing, records
from labcatalog.exceptions import EditError

MOOD = "instruments/example_mood.yaml"
STUDY = "studies/mock_study.yaml"


def changes(before: str, after: str) -> list[str]:
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line for line in lines if line[:1] in "+-" and line[:3] not in ("+++", "---")]


def test_tables_belong_to_their_files():
    assert list(records.tables_for(MOOD)) == ["items", "scores", "response_sets"]
    assert list(records.tables_for("labcatalog.yaml")) == ["datasets"]
    assert list(records.tables_for(STUDY)) == ["administrations"]
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
    text = editing.open_file(mock_project, MOOD).text.replace(
        "      - {value: 2, label: Often}
", "      # middle
      - {value: 2, label: Often}
"
    )
    rows = records.read_rows(text, "response_sets", records.OPTIONS)
    assert rows[1] == {records.ORIGIN: [0, 1], "id": "frequency", "value": "1", "label": "Sometimes"}
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
        "+      - {value: 1, label: Yes}",
        "+      - {value: 0, label: No}",
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
    text = editing.open_file(mock_project, STUDY).text.replace(
        "target: child}", "target: child, overrides: [{item: cs_1, dropped: true}]}"
    )
    rows = records.read_rows(text, "administrations", records.ADMINISTRATIONS)
    assert rows[1]["datasets"] == "parent_w1, parent_w2, parent_w3"
    rows[1]["reversed_in_data"] = True
    rows[1]["datasets"] = "parent_w1, parent_w2"
    rows[4]["target"] = "self"
    assert changes(text, records.write_rows(text, "administrations", records.ADMINISTRATIONS, rows)) == [
        "-  - {instrument: example_child_sleep, datasets: [parent_w1, parent_w2, parent_w3], target: child, overrides: [{item: cs_1, dropped: true}]}",
        "+  - {instrument: example_child_sleep, datasets: [parent_w1, parent_w2], target: child, overrides: [{item: cs_1, dropped: true}], reversed_in_data: true}",
        "-  - {instrument: example_demographics, datasets: [parent_w1, parent_w2, parent_w3]}",
        "+  - {instrument: example_demographics, datasets: [parent_w1, parent_w2, parent_w3], target: self}",
    ]


def test_bad_cells_and_per_language_text_are_reported():
    with pytest.raises(EditError, match="Min: 'a lot' is not a number"):
        records.write_rows("items: []\n", "items", records.ITEMS, [{"id": "x", "min": "a lot"}])
    with pytest.raises(EditError, match="Set: every row needs one"):
        records.write_rows("x: 1
", "response_sets", records.OPTIONS, [{"value": "1"}])
    with pytest.raises(EditError, match="empty has no options"):
        records.read_rows("response_sets:
  - {id: empty, options: []}
", "response_sets", records.OPTIONS)
    with pytest.raises(EditError, match="per language"):
        records.read_rows("items:\n  - {id: x, text: {en: Hi, es: Hola}}\n", "items", records.ITEMS)
