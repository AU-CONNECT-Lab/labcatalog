import math

import pandas as pd
import pytest

from labcatalog.config import DatasetConfig
from labcatalog.project import load_project
from labcatalog.resolve import ResolvedScore, resolve_catalog
from labcatalog.scoring import compute_score, compute_scores
from labcatalog.sources import LoadedDataset, load_datasets

FRAME = pd.DataFrame(
    {
        "a": ["1", "1", "7", "0"],
        "b": ["2", "-99", "", "3"],
        "c": ["3", "3", "", "0"],
    }
)


def make_score(**changes) -> ResolvedScore:
    fields = dict(
        key="x.total@d",
        instrument_id="x",
        score_id="total",
        dataset="d",
        label="Total",
        method="sum",
        columns=["a", "b", "c"],
        reverse_columns=["b"],
        reverse_bounds={"b": (0.0, 3.0)},
        valid_values={column: [0.0, 1.0, 2.0, 3.0] for column in "abc"},
        reversed_in_data=False,
        missing_rule="complete",
    )
    return ResolvedScore(**{**fields, **changes})


LOADED = LoadedDataset(
    config=DatasetConfig(
        name="d", modality="q", study="s", wave="1", reporter="r", source="csv", path="d.csv"
    ),
    frame=FRAME,
    id_column="a",
    group=None,
    source_path=None,
)


def values(score: ResolvedScore) -> list:
    return [None if math.isnan(v) else v for v in compute_score(LOADED, score)]


def test_complete_requires_every_item():
    # Row 1: 1 + (3 - 2) + 3. Rows 2 and 3 miss items; row 4: 0 + (3 - 3) + 0.
    assert values(make_score()) == [5, None, None, 0]


def test_prorate_fills_with_the_persons_mean():
    assert values(make_score(missing_rule="prorate", min_valid=2)) == [5, 6, None, 0]


def test_zero_counts_missing_items_as_zero():
    assert values(make_score(missing_rule="zero", min_valid=2)) == [5, 4, None, 0]


def test_mean_score():
    result = values(make_score(method="mean", missing_rule="prorate", min_valid=2))
    assert result == [pytest.approx(5 / 3), 2, None, 0]


def test_out_of_range_values_never_count():
    # Row 3 has a 7, which is not a response option, so it holds no valid answer.
    assert values(make_score(missing_rule="prorate", min_valid=1))[2] is None


def test_data_already_reversed():
    assert values(make_score(reversed_in_data=True))[0] == 6


def test_unavailable_items_give_no_score():
    assert values(make_score(unavailable_items=["d"])) == [None] * 4


def test_example_scores(mock_project):
    project = load_project(mock_project)
    scores = compute_scores(resolve_catalog(project), load_datasets(project))
    ems = scores["child_w1"]["example_mood.ems_total@child_w1"]
    assert ems.notna().sum() == 136
    assert round(ems.mean(), 2) == 5.51
