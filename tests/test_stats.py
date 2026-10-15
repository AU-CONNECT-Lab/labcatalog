import pandas as pd
import pytest

from labcatalog.pipeline import load_validated
from labcatalog.resolve import resolve_catalog
from labcatalog.scoring import compute_scores
from labcatalog.sources import load_datasets
from labcatalog.stats import cronbach_alpha, histogram, summarize


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
    assert eps4.n_valid + sum(eps4.missing.values()) + eps4.n_unexpected == eps4.n_total == 146
    assert set(eps4.missing) == {"blank", "refused", "not applicable", "don't know"}


def test_score_summary_of_the_example(mock_project):
    summary = summary_for(mock_project)
    ems = next(s for s in summary.scores if s.key == "example_mood.ems_total@child_w1")
    assert ems.n_valid == 136
    assert round(ems.mean, 2) == 5.51
    assert round(ems.alpha, 2) == 0.86
    assert ems.possible_range == (0, 18)
    assert sum(count for _, _, count in ems.histogram) == 136
    assert len(ems.item_total) == 6
    assert len(ems.item_correlations) == 6 and ems.item_correlations[0][0] == 1.0
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
    assert (parent.n_rows, parent.n_ids) == (146, 146)
    # " 1031P" gives no family ID until the lab fixes the space.
    assert parent.n_groups == 145
    assert sum(parent.collected_by_month.values()) == 146
    eps = next(c for c in parent.completeness if c.instrument_id == "example_parent_stress")
    assert eps.complete + eps.partial + eps.empty == 146


def test_retention_and_groups(mock_project):
    summary = summary_for(mock_project)
    wave2 = next(r for r in summary.retention if r.reporter == "parent" and r.wave == "2")
    assert wave2.n == 128 and wave2.n_from_previous + wave2.n_new == 128
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


def test_collected_by_day_adds_up_to_the_month_counts(mock_project):
    parent = next(d for d in summary_for(mock_project).datasets if d.dataset == "parent_w1")
    assert sum(parent.collected_by_day.values()) == sum(parent.collected_by_month.values())
