import pandas as pd

from labcatalog import defaults
from labcatalog.data import id_map
from labcatalog.data.id_map import Rule
from labcatalog.pipeline import run_catalog


def test_rules_apply_in_order():
    rules = [
        Rule(id_map.TRIM),
        Rule(id_map.PREFIX, "sub-"),
        Rule(id_map.SUFFIX, "_v2"),
        Rule(id_map.PAD, width=4),
        Rule(id_map.UPPER),
    ]
    assert id_map.rewrite(" sub-12c_v2 ", rules) == "0012C"
    assert id_map.rewrite("S-1003-C", [Rule(id_map.REPLACE, r"^S-(\d+)-", r"\1")]) == "1003C"
    assert id_map.rewrite("1001C", [Rule(id_map.PREFIX, "")]) == "1001C"
    assert id_map.rule_problem([Rule(id_map.REPLACE, "(")]) is not None


def test_proposals_flag_clashes_and_check_the_pattern_and_roster():
    rows = id_map.propose(
        ["sub-1001C", "1001C", "sub-1002C", "sub-1002C", "x"],
        [Rule(id_map.PREFIX, "sub-")],
        {"x": "1003C"},
        r"\d{4}[PC]",
        {"1001C", "1002C"},
    )
    by_old = {r.old: r for r in rows}
    assert list(by_old) == ["sub-1001C", "1001C", "sub-1002C", "x"]
    assert by_old["sub-1001C"].clash and by_old["1001C"].clash
    assert not by_old["sub-1002C"].clash and by_old["sub-1002C"].listed
    assert by_old["x"].new == "1003C" and by_old["x"].matches and by_old["x"].listed is False
    assert id_map.propose(["a"], [], {}, None, None)[0].matches is None


def test_saving_replaces_a_datasets_entries_and_skips_unchanged_ids(tmp_path):
    first = [id_map.Row("sub-1", "1", None, None), id_map.Row("2", "2", None, None)]
    assert id_map.save(tmp_path, "a", first) == 1
    id_map.save(tmp_path, "b", [id_map.Row("sub-1", "9", None, None)])
    id_map.save(tmp_path, "a", [id_map.Row("sub-1", "01", None, None)])
    assert id_map.mapping(tmp_path, "a") == {"sub-1": "01"}
    assert id_map.mapping(tmp_path, "b") == {"sub-1": "9"}


def test_reading_a_dataset_applies_its_corrections_and_the_checks_see_them(mock_project):
    before = run_catalog(mock_project)
    spaced = next(i for i in before.report.issues if i.code == "id_whitespace")
    name = spaced.details["dataset"]
    loaded = before.datasets[name]
    old = next(v for v in loaded.original_ids if v != v.strip())
    pd.DataFrame([{"dataset": name, "from": old, "to": old.strip()}]).to_csv(
        mock_project / defaults.ID_MAP_FILENAME, index=False
    )
    after = run_catalog(mock_project)
    assert old.strip() in set(after.datasets[name].frame[loaded.id_column])
    assert old in set(after.datasets[name].original_ids)
    assert not any(
        i.code == "id_whitespace" and i.details.get("dataset") == name for i in after.report.issues
    )


def test_a_broken_map_is_reported(tmp_path):
    pd.DataFrame(
        [
            {"dataset": "a", "from": "1", "to": "2"},
            {"dataset": "a", "from": "1", "to": "3"},
            {"dataset": "gone", "from": "4", "to": ""},
        ]
    ).to_csv(tmp_path / defaults.ID_MAP_FILENAME, index=False)
    found = id_map.check(tmp_path, {"a"})
    messages = " | ".join(i.message for i in found)
    assert "more than one new ID" in messages
    assert "does not have: gone" in messages and "no new ID" in messages
    assert {i.level for i in found} == {"error", "warning"}
