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
GENDER = "item:example_demographics.dem_gender@parent_w1"
EDUCATION = "item:example_demographics.dem_edu@parent_w1"


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


def run(result, sample, data, keys, build, tmp_path, m=5):
    plan = imputation.plan(data, keys, [], m, 1)
    frame = data.frame()
    file = (tmp_path / imputation.file_name(frame, plan)).as_posix()
    found, engine = script.run_code(result, sample, frame, build(plan, file), rscript())
    assert engine == script.R
    return frame, found


def test_scores_are_imputed_item_by_item_and_scored_again(result, sample):
    data = script.AnalysisData(result, sample)
    plan = imputation.plan(data, [STRESS, STRAIN, SLEEP, GENDER], [MOOD, SLEEP], 5, 7)
    stress_items = [f"eps_{n}_w1" for n in range(1, 7)]
    assert plan.items[:6] == stress_items and len(plan.items) == len(set(plan.items))
    assert plan.auxiliaries == ["ems_total_child_w1"] and plan.numbers == []
    assert plan.factors == ["dem_gender_w1"]
    code = imputation.impute_r(plan, "kept.rds")
    assert "m = 5, seed = 7" in code and 'imputation_file <- "kept.rds"' in code
    assert 'factor_columns <- c("dem_gender_w1")' in code
    assert f'x[["eps_mean_parent_w1"]] <- rowMeans(x[c("{stress_items[0]}"' in code
    assert 'x[["ecs_total_parent_w1"]] <- rowSums(' in code
    assert "1 other score that helps impute them." in code


def test_the_file_name_follows_the_data_and_the_choices(result, sample):
    data = script.AnalysisData(result, sample)
    plan = imputation.plan(data, [STRESS, SLEEP], [], 5, 1)
    frame = data.frame()
    name = imputation.file_name(frame, plan)
    assert name == imputation.file_name(frame.copy(), plan)
    assert name != imputation.file_name(frame, imputation.plan(data, [STRESS, SLEEP], [], 5, 2))
    changed = frame.copy()
    changed.loc[0, plan.items[0]] = None
    assert name != imputation.file_name(changed, plan)


@needs_mice
def test_pooled_correlations_cover_everyone_and_reuse_the_kept_imputation(result, sample, tmp_path):
    data = script.AnalysisData(result, sample)
    keys = [STRESS, SLEEP, MOOD]
    variables = [data.variable(k) for k in keys]

    def build(plan, file):
        return imputation.correlation_code(variables, "pearson", plan, file)

    frame, first = run(result, sample, data, keys, build, tmp_path)
    [kept] = list(tmp_path.glob("imputation_*.rds"))
    stamp = kept.stat().st_mtime_ns
    _, again = run(result, sample, data, keys, build, tmp_path)
    assert kept.stat().st_mtime_ns == stamp and first["correlations"].equals(again["correlations"])
    assert (first["correlations"]["n"] == len(frame)).all()
    available, _ = script.run_code(result, sample, frame, script.correlation_code(variables), None)
    pooled = first["correlations"].drop_duplicates(["r"]).set_index(["x", "y"])["r"]
    seen = available["correlations"].set_index(["x", "y"])["r"]
    assert (pooled.reindex(seen.index) - seen).abs().max() < 0.1


@needs_mice
def test_pooled_regressions_fit_every_imputed_data_set(result, sample, tmp_path):
    data = script.AnalysisData(result, sample)
    y, x = data.variable(MOOD), data.variable(STRESS)
    frame, found = run(
        result,
        sample,
        data,
        [MOOD, STRESS, SLEEP],
        lambda plan, file: imputation.regression_code([x], y, plan, file),
        tmp_path,
    )
    [pooled] = script.read_regressions(found, {x.column: STRESS}).values()
    available, _ = script.run_code(result, sample, frame, script.regression_code([x], y), None)
    [seen] = script.read_regressions(available, {x.column: STRESS}).values()
    assert pooled.correlation.n == len(frame) > seen.correlation.n
    assert abs(pooled.slope - seen.slope) < 0.25 * abs(seen.slope)
    assert pooled.correlation.low < pooled.correlation.r < pooled.correlation.high
    r_squared = found["regressions"]["r_squared"].iloc[0]
    assert abs(r_squared - pooled.correlation.r**2) < 0.05


@needs_mice
@pytest.mark.parametrize("group_key", [GENDER, EDUCATION])
def test_pooled_group_comparisons_keep_everyone_whose_group_is_known(
    result, sample, tmp_path, group_key
):
    data = script.AnalysisData(result, sample)
    group, outcome = data.item(group_key), data.variable(MOOD)
    plans = {}

    def build(plan, file):
        plans["found"] = imputation.comparison_plan(data.frame(), group, outcome, plan, file)
        return plans["found"].code

    frame, found = run(result, sample, data, [MOOD, STRESS, group_key], build, tmp_path)
    comparison = script.read_comparison(found, plans["found"])
    known = frame[group.column].isin([g for g, _ in group.options])
    assert sum(g.n for g in comparison.groups) <= known.sum()
    assert comparison.p is not None and comparison.effect is not None
    if comparison.test == script.STUDENT:
        first, second = comparison.groups
        assert comparison.low < first.mean - second.mean < comparison.high
    else:
        assert comparison.test == script.ANOVA and comparison.df2 > 0


@needs_mice
def test_the_summary_sets_imputed_values_beside_the_observed_ones(result, sample, tmp_path):
    data = script.AnalysisData(result, sample)
    frame, found = run(
        result,
        sample,
        data,
        [SLEEP, GENDER],
        lambda plan, file: imputation.summary_code(plan, file),
        tmp_path,
        m=3,
    )
    columns, _ = imputation.read_summary(found)
    for c in columns:
        assert c.missing == frame[c.column].isna().sum()
        assert (c.imputed_mean is None) == (c.missing == 0)
    long = found["imputed_long"]
    assert sorted(long[".imp"].unique()) == [0, 1, 2, 3] and len(long) == 4 * len(frame)
    imputed = long[long[".imp"] == 1]
    assert imputed["ecs_total_parent_w1"].notna().all()
