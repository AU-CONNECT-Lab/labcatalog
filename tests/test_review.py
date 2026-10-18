from labcatalog.gui import review
from labcatalog.pipeline import run_catalog


def test_each_data_file_shows_its_answers_problems_and_scores(mock_project):
    result = run_catalog(mock_project)
    rows = {row.dataset: row for row in review.review_rows(result)}
    assert set(rows) == {d.dataset for d in result.summary.datasets}
    child = rows["child_w1"]
    summary = next(d for d in result.summary.datasets if d.dataset == "child_w1")
    assert (child.rows, child.ids, child.unexpected) == (
        summary.n_rows,
        summary.n_ids,
        summary.n_unexpected,
    )
    assert 0 < child.answered <= 1
    total = next(s for s in child.scores if s.label == "EMS total score")
    found = next(s for s in result.summary.scores if s.key == "example_mood.ems_total@child_w1")
    assert (total.n, total.alpha) == (found.n_valid, found.alpha)
    assert sum(total.histogram) == found.n_valid
    assert sum(r.unexpected for r in rows.values()) > 0
    assert any(r.warnings for r in rows.values())


def test_the_bars_scale_to_the_tallest():
    drawn = review.bars([0, 2, 4])
    assert drawn.count("<rect") == 3
    assert f'height="{review.BAR_HEIGHT:.1f}"' in drawn and 'height="0.0"' in drawn
