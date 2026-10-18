import shutil
from glob import glob

import pytest

from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, imputation
from labcatalog.stats import analysis_script as script
from labcatalog.stats.rbridge import IMPUTATION_PACKAGES, r_status

STRESS = "example_parent_stress.eps_mean@parent_w1"
STRAIN = "example_parent_stress.eps_strain@parent_w1"
SLEEP = "example_child_sleep.ecs_total@parent_w1"
MOOD = "example_mood.ems_total@child_w1"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


needs_mice = pytest.mark.skipif(
    rscript() is None or bool(r_status(rscript(), IMPUTATION_PACKAGES).missing),
    reason="R with mice and miceadds is not installed",
)


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


@pytest.fixture
def sample(result):
    return analysis.build_sample(result, ["parent_w1", "child_w1"], True)


def test_scores_are_imputed_item_by_item_and_scored_again(result, sample):
    data = script.AnalysisData(result, sample)
    plan = imputation.plan(data, [STRESS, STRAIN, SLEEP], [MOOD, SLEEP], 5, 7)
    stress_items = [f"eps_{n}_w1" for n in range(1, 7)]
    assert plan.items[:6] == stress_items and len(plan.items) == len(set(plan.items))
    assert plan.auxiliaries == ["ems_total_child_w1"] and plan.numbers == []
    code = imputation.impute_r(plan)
    assert "m = 5, seed = 7" in code
    assert f'x[["eps_mean_parent_w1"]] <- rowMeans(x[c("{stress_items[0]}"' in code
    assert 'x[["ecs_total_parent_w1"]] <- rowSums(' in code
    assert "Imputed: the items of the chosen scores; 1 other score that helps impute them." in code


@needs_mice
def test_pooled_correlations_cover_everyone_and_repeat_with_the_seed(result, sample):
    data = script.AnalysisData(result, sample)
    keys = [STRESS, SLEEP, MOOD]
    variables = [data.variable(k) for k in keys]
    plan = imputation.plan(data, keys, [], 5, 1)
    frame = data.frame()
    code = imputation.correlation_code(variables, "pearson", plan)
    first, engine = script.run_code(result, sample, frame, code, rscript())
    again, _ = script.run_code(result, sample, frame, code, rscript())
    assert engine == script.R and first["correlations"].equals(again["correlations"])
    assert (first["correlations"]["n"] == len(frame)).all()
    available, _ = script.run_code(result, sample, frame, script.correlation_code(variables), None)
    pooled = first["correlations"].drop_duplicates(["r"]).set_index(["x", "y"])["r"]
    seen = available["correlations"].set_index(["x", "y"])["r"]
    assert (pooled.reindex(seen.index) - seen).abs().max() < 0.1


@needs_mice
def test_the_summary_sets_imputed_values_beside_the_observed_ones(result, sample):
    data = script.AnalysisData(result, sample)
    plan = imputation.plan(data, [SLEEP], [MOOD], 3, 1)
    frame = data.frame()
    found, _ = script.run_code(result, sample, frame, imputation.summary_code(plan), rscript())
    columns, _ = imputation.read_summary(found)
    assert [c.column for c in columns] == plan.columns
    for c in columns:
        assert c.missing == frame[c.column].isna().sum()
        assert (c.imputed_mean is None) == (c.missing == 0)
