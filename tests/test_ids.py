import pandas as pd

from labcatalog.ids import family_ids, normalize_ids, parse_id_rules


def normalize(values, raw_rules):
    rules, problems = parse_id_rules(raw_rules)
    assert problems == []
    return normalize_ids(pd.Series(values), rules).tolist()


def test_rules_apply_in_order():
    raw = ["strip", {"remove_prefix": "sub-"}, {"zero_pad": 4}, {"add_suffix": "C"}]
    assert normalize([" sub-12 ", "0034C"], raw) == ["0012C", "0034C"]


def test_add_prefix_only_where_missing():
    assert normalize(["sub-1001", "1002"], [{"add_prefix": "sub-"}]) == ["sub-1001", "sub-1002"]


def test_regex_replace():
    raw = [{"regex_replace": {"pattern": r"^S(\d+)$", "replacement": r"\1"}}]
    assert normalize(["S1001", "1002"], raw) == ["1001", "1002"]


def test_bad_rules_are_described():
    _, problems = parse_id_rules(["trim", {"zero_pad": "4"}, {"regex_replace": {"pattern": "("}}])
    assert len(problems) == 3
    assert problems[0].startswith("rule 1:")


def test_family_from_id():
    assert family_ids(pd.Series(["1001P", "1001C", "x"]), r"^(\d{4})").tolist()[:2] == [
        "1001",
        "1001",
    ]
