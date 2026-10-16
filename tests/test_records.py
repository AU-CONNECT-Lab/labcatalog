import difflib

import pytest

from labcatalog import editing, records
from labcatalog.exceptions import EditError

MOOD = "instruments/example_mood.yaml"


def changes(before: str, after: str) -> list[str]:
    lines = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line for line in lines if line[:1] in "+-" and line[:3] not in ("+++", "---")]


def test_tables_belong_to_their_files():
    assert list(records.tables_for(MOOD)) == ["items", "scores"]
    assert list(records.tables_for("labcatalog.yaml")) == ["datasets"]
    assert records.tables_for("studies/mock_study.yaml") == {}
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


def test_bad_cells_and_per_language_text_are_reported():
    with pytest.raises(EditError, match="Min: 'a lot' is not a number"):
        records.write_rows("items: []\n", "items", records.ITEMS, [{"id": "x", "min": "a lot"}])
    with pytest.raises(EditError, match="per language"):
        records.read_rows("items:\n  - {id: x, text: {en: Hi, es: Hola}}\n", "items", records.ITEMS)
