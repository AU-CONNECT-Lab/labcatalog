import re
from dataclasses import replace
from itertools import pairwise

import pandas as pd
import pytest
from conftest import NAMED_WAVES, VISIT, name_waves

from labcatalog.config import DatasetConfig, MissingCode, ProjectConfig
from labcatalog.data.resolve import Catalog, ResolvedScore, ResolvedVariable, resolve_catalog
from labcatalog.data.scoring import compute_score, compute_scores
from labcatalog.pipeline import load_validated
from labcatalog.schema import ResponseOption
from labcatalog.sources import LoadedDataset, load_datasets
from labcatalog.stats.link import link
from labcatalog.stats.summary import (
    cronbach_alpha,
    histogram,
    modality_counts,
    retained,
    retention,
    stability,
    summarize,
    summarize_dataset,
    summarize_score,
    summarize_variable,
    wave_order,
    waves_of_scores,
)

REFUSED = ProjectConfig(
    project={"name": "p"}, missing_codes=[MissingCode(code=-99, label="refused")]
)


def loaded_with(name: str = "d", wave: str = "1", **columns: list[str]) -> LoadedDataset:
    config = DatasetConfig(
        name=name, modality="q", study="s", wave=wave, reporter="r", source="csv", path="d.csv"
    )
    return LoadedDataset(config, pd.DataFrame(columns), "id", None, None)


def variable(column: str, kind: str = "choice", options: tuple = ()) -> ResolvedVariable:
    return ResolvedVariable(
        column=column,
        instrument_id="x",
        item_id=column,
        dataset="d",
        study="s",
        wave="1",
        reporter="r",
        modality="q",
        text={"default": column},
        type=kind,
        response_options=[ResponseOption(value=v, label=str(v)) for v in options],
        reverse=False,
        reversed_in_data=False,
    )


def summary_for(root):
    project, issues = load_validated(root)
    assert project is not None, issues
    catalog = resolve_catalog(project)
    datasets = load_datasets(project)
    return summarize(catalog, datasets, compute_scores(catalog, datasets), project.config)


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_variable_counts_add_up(mock_project):
    summary = summary_for(mock_project)
    eps4 = next(v for v in summary.variables if v.column == "eps_4_w1")
    assert eps4.n_unexpected == 1
    assert list(eps4.value_counts) == ["1", "2", "3", "4", "5"]
    assert eps4.n_valid + sum(eps4.missing.values()) + eps4.n_unexpected == eps4.n_total == 191
    assert set(eps4.missing) == {"blank", "refused", "not applicable", "don't know"}


def test_score_summary_of_the_example(mock_project):
    summary = summary_for(mock_project)
    ems = next(s for s in summary.scores if s.key == "example_mood.ems_total@child_w1")
    assert ems.n_valid == 216
    assert round(ems.mean, 2) == 11.46
    assert round(ems.alpha, 2) == 0.90
    assert ems.possible_range == (0, 27)
    assert sum(count for _, _, count in ems.histogram) == 216
    assert len(ems.item_total) == 9
    assert len(ems.item_correlations) == 9 and ems.item_correlations[0][0] == 1.0
    assert all(r > 0 for row in ems.item_correlations for r in row)


def test_unmarked_reverse_item_shows_negative_correlations(mock_project):
    edit(
        mock_project / "instruments" / "example_mood.yaml",
        "{id: ems_1, text: I felt happy., reverse: true}",
        "{id: ems_1, text: I felt happy.}",
    )
    summary = summary_for(mock_project)
    ems = next(s for s in summary.scores if s.key == "example_mood.ems_total@child_w1")
    assert all(r < 0 for r in ems.item_correlations[0][1:])
    assert ems.item_total[0].r < 0


def test_dataset_summary(mock_project):
    summary = summary_for(mock_project)
    parent = next(d for d in summary.datasets if d.dataset == "parent_w1")
    assert (parent.n_rows, parent.n_ids) == (191, 191)
    # " 1031P" gives no family ID until the lab fixes the space.
    assert parent.n_groups == 190
    assert sum(parent.collected_by_month.values()) == 191
    eps = next(c for c in parent.completeness if c.instrument_id == "example_parent_stress")
    assert eps.complete + eps.partial + eps.empty == 191


def test_retention_and_groups(mock_project):
    summary = summary_for(mock_project)
    wave2 = next(r for r in summary.retention if r.reporter == "parent" and r.wave == "2")
    assert wave2.n == 170 and wave2.n_from_previous + wave2.n_new == 170
    assert summary.group_name == "family"
    assert [g.wave for g in summary.groups] == ["1", "2", "3"]


def test_correlations_link_reporters_by_group(mock_project):
    summary = summary_for(mock_project)
    wave1 = next(c for c in summary.correlations if c.wave == "1")
    ems = wave1.keys.index("example_mood.ems_total@child_w1")
    eps = wave1.keys.index("example_parent_stress.eps_mean@parent_w1")
    assert 0.4 < wave1.r[ems][eps] < 0.5
    assert wave1.n[ems][eps] > 120


def test_correlating_by_id_cannot_link_parent_and_child(mock_project):
    edit(mock_project / "labcatalog.yaml", "correlate_by: family", "correlate_by: id")
    wave1 = next(c for c in summary_for(mock_project).correlations if c.wave == "1")
    ems = wave1.keys.index("example_mood.ems_total@child_w1")
    eps = wave1.keys.index("example_parent_stress.eps_mean@parent_w1")
    assert wave1.n[ems][eps] == 0 and wave1.r[ems][eps] is None


def test_alpha_and_histogram_edge_cases():
    assert cronbach_alpha(pd.DataFrame({"a": [1, 2], "b": [1, 2]})) is None
    assert cronbach_alpha(pd.DataFrame({"a": [1, 2, 3], "b": [1, 2, 3]})) == pytest.approx(1.0)
    bins = histogram(pd.Series([7.2, 7.0, 0.0]), 0, 18, integer=True)
    assert [count for left, _, count in bins if left == 6.5] == [2]


def test_stability_pairs_adjacent_waves_and_retained_scores_need_every_wave(mock_project):
    summary = summary_for(mock_project)
    ems = [s for s in summary.stability if s.score_id == "ems_total"]
    assert [(s.reporter, s.from_wave, s.to_wave) for s in ems] == [
        ("child", "1", "2"),
        ("child", "2", "3"),
    ]
    assert all(0 < s.r < 1 for s in ems)
    kept = [r for r in summary.retained if r.score_id == "ems_total"]
    assert [r.wave for r in kept] == ["1", "2", "3"]
    [n] = {r.n for r in kept}
    assert 0 < n <= min(s.n for s in ems)


def test_each_dataset_with_an_occasion_is_an_occasion_of_its_own_across_waves(visit_project):
    summary = summary_for(visit_project)
    occasions = ["1", "2", *[f"2 ({time}, {interaction})" for _, time, interaction in VISIT], "3"]
    ems = [s for s in summary.stability if s.score_id == "ems_total"]
    assert [(s.from_wave, s.to_wave) for s in ems] == list(pairwise(occasions))
    assert all(s.n > 0 and s.r is not None for s in ems)
    kept = [r for r in summary.retained if r.score_id == "ems_total"]
    assert [r.wave for r in kept] == occasions and all(r.n > 0 for r in kept)


def test_one_reporter_answering_about_two_targets_has_a_series_for_each():
    totals = {
        "self_w1": [4, 6, 8, 10, 12],
        "self_w2": [5, 6, 9, 11, 12],
        "child_w1": [16, 14, 12, 10, 8],
        "child_w2": [8, 16, 10, 14, 12],
    }
    datasets = {
        name: loaded_with(name, name[-1], id=[f"{name[0]}{i}" for i in range(5)]) for name in totals
    }
    catalog = Catalog(
        variables=[],
        scores=[
            ResolvedScore(
                key=f"x.total@{name}",
                instrument_id="x",
                score_id="total",
                dataset=name,
                label="Total",
                method="sum",
                columns=[],
                reverse_columns=[],
                reverse_bounds={},
                valid_values={},
                reversed_in_data=False,
                missing_rule="complete",
                target=name.split("_")[0],
            )
            for name in totals
        ],
    )
    scores = {name: pd.DataFrame({f"x.total@{name}": t}) for name, t in totals.items()}
    config = ProjectConfig(
        project={"name": "p"}, studies={"s": {}}, datasets=[d.config for d in datasets.values()]
    )
    found = waves_of_scores(catalog, datasets, scores, config)
    expected = {
        t: pd.Series(totals[f"{t}_w1"]).corr(pd.Series(totals[f"{t}_w2"]))
        for t in ("self", "child")
    }
    assert {s.target: (s.r, s.n) for s in stability(found, config)} == {
        t: (pytest.approx(r), 5) for t, r in expected.items()
    }
    assert {(r.target, r.wave, r.n) for r in retained(found)} == {
        (t, w, 5) for t in ("self", "child") for w in ("1", "2")
    }


def test_collection_is_given_by_month_and_never_by_day(mock_project):
    parent = next(d for d in summary_for(mock_project).datasets if d.dataset == "parent_w1")
    months = list(parent.collected_by_month)
    assert parent.collected == f"{months[0]} to {months[-1]}"
    assert re.fullmatch(r"\d{4}-\d\d to \d{4}-\d\d", parent.collected)
    # The snapshot date is the project's own, not a person's.
    shown = parent.model_dump(exclude={"snapshot_date"}).values()
    assert not any(re.search(r"\d{4}-\d\d-\d\d", str(v)) for v in shown)


def test_number_and_text_items(mock_project):
    summary = summary_for(mock_project)
    by_column = {v.column: v for v in summary.variables}
    age = by_column["dem_age_w2"]
    assert (age.n_valid, age.n_unexpected, age.value_counts) == (167, 1, {})
    assert 3 <= age.minimum <= age.median <= age.maximum <= 18
    comment = by_column["dem_comment_w2"]
    assert comment.n_valid + comment.missing["blank"] == comment.n_total
    assert comment.mean is None
    parent = next(d for d in summary.datasets if d.dataset == "parent_w2")
    background = next(c for c in parent.completeness if c.instrument_id == "example_demographics")
    # The optional comment does not make everyone a partial responder.
    assert background.n_items == 4 and background.complete > 100


def test_a_missing_code_written_as_another_form_of_its_number_is_missing():
    loaded = loaded_with(
        id=["A1", "A2", "A3", "A4"],
        hours=["8.0", "-99.0", "7.0", "9.0"],
        x1=["1", "-99.0", "-99.00", "-99"],
    )
    hours = summarize_variable(loaded, variable("hours", "number"), REFUSED)
    assert (hours.n_valid, hours.missing["refused"], hours.mean, hours.minimum) == (3, 1, 8, 7)
    x1 = summarize_variable(loaded, variable("x1", options=(1, 2)), REFUSED)
    assert (x1.n_valid, x1.missing["refused"], x1.n_unexpected) == (1, 3, 0)


def test_missing_codes_that_share_a_label_are_counted_together():
    config = ProjectConfig(
        project={"name": "p"},
        missing_codes=[
            MissingCode(code=-99, label="missing"),
            MissingCode(code=-999, label="missing"),
        ],
    )
    loaded = loaded_with(id=["A1", "A2", "A3", "A4"], x1=["1", "-99", "-999", "-999"])
    x1 = summarize_variable(loaded, variable("x1", options=(1, 2)), config)
    assert (x1.missing, x1.n_unexpected) == ({"blank": 0, "missing": 3}, 0)


def test_rows_without_an_id_are_nobody():
    datasets = {
        "d1": loaded_with("d1", "1", id=["A1", "", "A3", "  "]),
        "d2": loaded_with("d2", "2", id=["A1", "", "A4"]),
    }
    empty = Catalog(variables=[], scores=[])
    assert [summarize_dataset(d, empty, [], REFUSED).n_ids for d in datasets.values()] == [2, 2]
    config = ProjectConfig(project={"name": "p"}, studies={"s": {}})
    kept = [(r.wave, r.n, r.n_from_previous, r.n_new) for r in retention(datasets, config)]
    assert kept == [("1", 2, None, None), ("2", 2, 1, 1)]
    counted = [(m.wave, m.n, m.n_from_previous) for m in modality_counts(datasets, config)]
    assert counted == [("1", 2, None), ("2", 2, 1)]
    rows = link(datasets, ["d1", "d2"], "id").rows
    assert (rows["d1"].to_dict(), rows["d2"].to_dict()) == (
        {"id:A1": 0, "id:A3": 2},
        {"id:A1": 0, "id:A4": 2},
    )


def test_a_person_and_a_group_written_alike_stay_apart():
    # Family 5 has children 2 and 7, family 2 has child 9; parent 5 has no family.
    children = replace(loaded_with("c", id=["2", "7", "9"]), group=pd.Series(["5", "5", "2"]))
    parents = replace(loaded_with("p", id=["30", "31", "5"]), group=pd.Series(["5", "2", None]))
    rows = link({"c": children, "p": parents}, ["c", "p"], "family").rows
    pairs = {
        (children.frame["id"][rows["c"][key]], parents.frame["id"][rows["p"][key]])
        for key in rows["c"].index.intersection(rows["p"].index)
    }
    assert pairs == {("2", "30"), ("7", "30"), ("9", "31")}
    assert "id:5" in rows["p"].index


@pytest.mark.parametrize(("method", "possible"), [("sum", (0, 16)), ("mean", (0, 4))])
def test_a_score_that_counts_missing_items_as_zero_fits_its_range(method, possible):
    columns = ["a", "b", "c", "d"]
    score = ResolvedScore(
        key="x.total@d",
        instrument_id="x",
        score_id="total",
        dataset="d",
        label="Total",
        method=method,
        columns=columns,
        reverse_columns=[],
        reverse_bounds={},
        valid_values={c: [1.0, 2.0, 3.0, 4.0] for c in columns},
        reversed_in_data=False,
        missing_rule="zero",
        min_valid=2,
    )
    # Two items answered with 1 sum to 2, below the 4 of answering every item with 1.
    loaded = loaded_with(id=["A1", "A2"], a=["1", "2"], b=["1", "2"], c=["", "2"], d=["", "2"])
    summary = summarize_score(loaded, score, compute_score(loaded, score))
    assert summary.possible_range == possible
    assert sum(count for _, _, count in summary.histogram) == summary.n_valid == 2


def test_a_prorated_sum_of_items_with_other_ranges_fits_its_range():
    score = ResolvedScore(
        key="x.total@d",
        instrument_id="x",
        score_id="total",
        dataset="d",
        label="Total",
        method="sum",
        columns=["a", "b"],
        reverse_columns=[],
        reverse_bounds={},
        valid_values={"a": [0.0, 1.0, 2.0, 3.0], "b": [1.0, 2.0, 3.0, 4.0, 5.0]},
        reversed_in_data=False,
        missing_rule="prorate",
        min_valid=1,
    )
    # Only a, answered 0, prorates to 0, below the lowest sum of 1; only b, answered 5, to 10.
    loaded = loaded_with(id=["A1", "A2", "A3"], a=["0", "", "1"], b=["", "5", "2"])
    summary = summarize_score(loaded, score, compute_score(loaded, score))
    assert summary.possible_range == (0, 10)
    assert sum(count for _, _, count in summary.histogram) == summary.n_valid == 3


def test_waves_follow_the_order_the_study_writes_them(mock_project):
    before = summary_for(mock_project)
    name_waves(mock_project)
    after = summary_for(mock_project)
    named = NAMED_WAVES.get
    assert [(r.reporter, r.wave, r.n, r.n_from_previous) for r in after.retention] == [
        (r.reporter, named(r.wave), r.n, r.n_from_previous) for r in before.retention
    ]
    assert [(m.modality, m.wave, m.previous_wave, m.n_new) for m in after.modalities] == [
        (m.modality, named(m.wave), named(m.previous_wave), m.n_new) for m in before.modalities
    ]
    assert [(s.score_id, s.from_wave, s.to_wave, s.r) for s in after.stability] == [
        (s.score_id, named(s.from_wave), named(s.to_wave), s.r) for s in before.stability
    ]
    assert [(r.score_id, r.wave, r.mean) for r in after.retained] == [
        (r.score_id, named(r.wave), r.mean) for r in before.retained
    ]
    assert [g.wave for g in after.groups] == ["baseline", "6m", "12m"]
    assert [c.wave for c in after.correlations] == [named(c.wave) for c in before.correlations]


def test_waves_the_study_does_not_list_come_last_by_name():
    config = ProjectConfig(
        project={"name": "p"}, studies={"s": {"waves": {"T1": {}, "T2": {}, "T10": {}}}}
    )
    waves = ["x", "T10", "11", "T2", "3", "T1"]
    assert sorted(waves, key=wave_order(config, "s")) == ["T1", "T2", "T10", "3", "11", "x"]
