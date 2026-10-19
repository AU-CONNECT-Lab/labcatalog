from labcatalog.gui import review
from labcatalog.pipeline import run_catalog


def test_the_waves_of_one_reporters_files_share_a_table_of_scores(mock_project):
    result = run_catalog(mock_project)
    groups = review.review_groups(result)
    child = next(g for g in groups if [w.dataset for w in g.waves][:1] == ["child_w1"])
    assert [w.dataset for w in child.waves] == ["child_w1", "child_w2", "child_w3"]
    assert len({w.color for w in child.waves}) == 3
    first = child.waves[0]
    summary = next(d for d in result.summary.datasets if d.dataset == "child_w1")
    assert (first.rows, first.ids, first.unexpected) == (
        summary.n_rows,
        summary.n_ids,
        summary.n_unexpected,
    )
    assert 0 < first.answered <= 1
    total = next(line for line in child.scores if line.label == "EMS total score")
    assert len(total.waves) == 3 and all(total.waves)
    found = next(s for s in result.summary.scores if s.key == "example_mood.ems_total@child_w1")
    wave_1 = total.waves[0]
    assert (wave_1.n, wave_1.alpha) == (found.n_valid, found.alpha)
    assert wave_1.missing == summary.n_rows - found.n_valid
    assert sum(wave_1.histogram) == found.n_valid
    every = [d.dataset for d in result.summary.datasets]
    assert sorted(w.dataset for g in groups for w in g.waves) == sorted(every)


def test_the_waves_are_drawn_on_one_scale():
    drawn = review.overlay([("#111111", [0, 2, 4]), ("#222222", [1, 1]), ("#333333", [])])
    assert drawn.count("<polyline") == 2
    assert f',{review.PLOT_HEIGHT:.1f}"' in drawn or f",{review.PLOT_HEIGHT:.1f} " in drawn
    assert review.overlay([("#111111", [])]) == ""


def test_each_wave_can_be_drawn_apart_on_one_scale():
    drawn = review.separate([("#111111", [0, 2, 4]), ("#222222", [1, 1])])
    assert drawn.count("<svg") == 2 and drawn.count("<rect") == 5
    assert f'height="{review.PLOT_HEIGHT:.1f}" fill="#111111"' in drawn
