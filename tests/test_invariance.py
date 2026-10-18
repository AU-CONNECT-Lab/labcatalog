import shutil
import subprocess
from glob import glob

import pandas as pd
import pytest

from labcatalog.config import FreedParameter
from labcatalog.data.scoring import score_items
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, group_invariance, invariance
from labcatalog.stats.analysis import item_variable
from labcatalog.stats.cfa import SUBSCALES
from labcatalog.stats.rbridge import CFA_PACKAGES, r_status


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


def r_ready() -> bool:
    return rscript() is not None and not r_status(rscript(), CFA_PACKAGES).missing


needs_r = pytest.mark.skipif(not r_ready(), reason="R with lavaan and semTools is not installed")


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def models_of(result):
    return {
        m.instrument_id: m
        for m in invariance.build_models(result.project, result.catalog, result.datasets)
    }


def test_each_instrument_given_in_several_waves_gets_its_subscale_model(result):
    models = models_of(result)
    assert set(models) == {
        "example_mood",
        "example_parent_stress",
        "example_child_sleep",
        "example_worries_temper",
    }
    mood = models["example_mood"]
    assert (mood.study, mood.reporter, mood.kind) == ("mock_study", "child", SUBSCALES)
    assert list(mood.factors) == ["ems_sadness", "ems_worry", "ems_low_positive"]
    assert list(mood.occasions) == ["1", "2", "3"]


def test_wave_data_are_the_reversed_items_of_people_who_answered_all(result):
    mood = models_of(result)["example_mood"]
    loaded = result.datasets["child_w1"]
    parts = []
    for score_id, items in mood.factors.items():
        score = next(
            s for s in result.catalog.scores if s.key == f"example_mood.{score_id}@child_w1"
        )
        parts.append(score_items(loaded, score).set_axis(items, axis=1))
    expected = pd.concat(parts, axis=1).dropna()
    expected.index = loaded.frame[loaded.id_column].to_numpy()[expected.index]
    expected = expected[sorted(expected.columns, key=list(mood.occasions["1"].columns).index)]
    assert mood.occasions["1"].equals(expected)
    assert set(mood.occasions["1"].columns) == {f"ems_{i}" for i in range(1, 10)}


def test_r_names_in_messages_become_items_and_waves(result, tmp_path):
    mood = models_of(result)["example_mood"]
    _, original = invariance.write_model(tmp_path, 1, mood, "wlsmv")
    first = list(mood.occasions["3"].columns)[0]
    message = "categories differ: x1_t1, x1_t3; factor f2_t2"
    assert invariance.readable(message, original) == (
        f"categories differ: {first} (wave 1), {first} (wave 3); factor ems_worry (wave 2)"
    )
    data = pd.read_csv(tmp_path / "m1.csv")
    assert len(data) == len(set().union(*(set(f.index) for f in mood.occasions.values())))


@needs_r
def test_steps_add_constraints_and_compare_with_the_step_before(result):
    mood = models_of(result)["example_mood"]
    mood.occasions = {wave: mood.occasions[wave] for wave in ("1", "2")}
    [test] = invariance.fit_models([mood], rscript())
    assert test.problem is None
    assert test.n == {"1": len(mood.occasions["1"]), "2": len(mood.occasions["2"])}
    assert [s.step for s in test.steps] == list(invariance.STEPS)
    assert all(s.problem is None for s in test.steps)
    dfs = [s.fit["df"] for s in test.steps]
    assert dfs == sorted(dfs) and dfs[0] < dfs[-1]
    assert test.steps[0].chisq_diff is None
    assert all(s.df_diff > 0 and 0 <= s.p_diff <= 1 for s in test.steps[1:])


@needs_r
def test_continuous_items_have_no_thresholds_step_or_option_check(result):
    stress = models_of(result)["example_parent_stress"]
    # An option nobody chose in one wave only matters for ordered items.
    stress.occasions["3"]["eps_1"] = stress.occasions["3"]["eps_1"].replace(5.0, 4.0)
    [test] = invariance.fit_models([stress], rscript(), "ml")
    assert test.problem is None
    assert [s.step for s in test.steps] == ["configural", "metric", "scalar"]
    assert all(s.problem is None and s.fit["srmr"] is not None for s in test.steps)
    assert all(s.df_diff > 0 for s in test.steps[1:])


@needs_r
def test_mlr_gives_robust_fit_and_scaled_differences(result):
    stress = models_of(result)["example_parent_stress"]
    [ml] = invariance.fit_models([stress], rscript(), "ml")
    [mlr] = invariance.fit_models([stress], rscript(), "mlr")
    assert (ml.estimator, mlr.estimator) == ("ml", "mlr")
    assert [s.step for s in mlr.steps] == ["configural", "metric", "scalar"]
    assert all(s.problem is None and s.df_diff > 0 for s in mlr.steps[1:])
    # The robust chi-square is the ML one divided by a scaling factor.
    assert mlr.steps[0].fit["df"] == ml.steps[0].fit["df"]
    assert mlr.steps[0].fit["chisq"] != pytest.approx(ml.steps[0].fit["chisq"])


def test_an_option_nobody_chose_in_one_wave_stops_the_model_before_r(result):
    stress = models_of(result)["example_parent_stress"]
    stress.occasions["3"]["eps_1"] = stress.occasions["3"]["eps_1"].replace(5.0, 4.0)
    [test] = invariance.fit_models([stress], "C:/no/such/Rscript.exe")
    assert test.steps == []
    assert test.n == {wave: len(frame) for wave, frame in stress.occasions.items()}
    assert "eps_1 in wave 3 (5)" in test.problem
    shifted = {"1": pd.DataFrame({"a": [1.0, 2.0]}), "2": pd.DataFrame({"a": [2.0, 3.0]})}
    stress.occasions = shifted
    assert "a in wave 1 (3); a in wave 2 (1)" in invariance.unchosen_options(stress)


def free(result, *entries):
    result.project.config.stats.invariance_free = [FreedParameter(**e) for e in entries]
    return models_of(result)


def test_freed_items_become_lavaan_exceptions_on_every_occasion(result):
    mood = free(
        result,
        {"instrument": "example_mood", "item": "ems_2", "parameter": "loading"},
        {"instrument": "example_mood", "item": "ems_4", "parameter": "threshold"},
        {"instrument": "example_mood", "item": "ems_5", "parameter": "intercept"},
        {"instrument": "example_mood", "item": "ems_6", "parameter": "loading", "across": "x.y"},
    )["example_mood"]
    assert [f.item for f in mood.freed] == ["ems_2", "ems_4", "ems_5"]
    x = {item: stem for stem, item in invariance.item_names(mood).items()}
    factor = 1 + next(j for j, items in enumerate(mood.factors.values()) if "ems_2" in items)
    categories = len(set(mood.occasions["1"]["ems_4"]))
    loading, intercept = f"f{factor} =~ {x['ems_2']}", f"{x['ems_5']} ~1"
    thresholds = [f"{x['ems_4']} | t{k}" for k in range(1, categories)]
    assert invariance.partial(mood, "wlsmv") == [loading, *thresholds, intercept]
    assert invariance.partial(mood, "ml") == [loading, intercept]


@needs_r
def test_a_freed_loading_frees_a_constraint_and_score_tests_name_each_item(result):
    two_waves = {"instrument": "example_mood", "item": "ems_2", "parameter": "loading"}
    held, freed = (
        models_of(result)["example_mood"],
        free(result, two_waves)["example_mood"],
    )
    for model in (held, freed):
        model.occasions = {wave: model.occasions[wave] for wave in ("1", "2")}
    [before, after] = invariance.fit_models([held, freed], rscript())
    metric = [next(s for s in t.steps if s.step == "metric") for t in (before, after)]
    assert metric[0].fit["df"] - metric[1].fit["df"] == 1
    assert after.freed == freed.freed
    scores = invariance.score_tests(held, "metric", rscript())
    assert sorted(s.item for s in scores) == [f"ems_{i}" for i in range(1, 10)]
    assert all(s.parameter == "loading" and s.df == 1 and 0 <= s.p <= 1 for s in scores)
    # A freed item has no constraint left to test.
    assert "ems_2" not in [s.item for s in invariance.score_tests(freed, "metric", rscript())]


def add_parent_mood(project):
    # Parents rate their child's mood at wave 1, here with the child's wave 2 answers.
    data = pd.read_csv(project / "data" / "child_w2.csv", dtype=str)
    data["pid"] = data["pid"].str.replace("C", "P")
    data.to_csv(project / "data" / "parent_mood_w1.csv", index=False)
    mapping = pd.read_csv(project / "maps" / "child_w2.csv", dtype=str)
    mood = mapping[mapping["instrument"].isna() | (mapping["instrument"] == "example_mood")]
    mood.to_csv(project / "maps" / "parent_mood_w1.csv", index=False)
    config = project / "labcatalog.yaml"
    line = next(x for x in config.read_text().splitlines() if "{name: child_w1," in x)
    extra = line.replace("child_w1", "parent_mood_w1").replace(
        "reporter: child", "reporter: parent"
    )
    config.write_text(config.read_text().replace(line, f"{line}\n{extra}"))
    study = project / "studies" / "mock_study.yaml"
    line = next(x for x in study.read_text().splitlines() if "instrument: example_mood" in x)
    extra = line.replace("[child_w1, child_w2, child_w3]", "[parent_mood_w1]")
    study.write_text(study.read_text().replace(line, f"{line}\n{extra.replace('self', 'child')}"))
    return run_catalog(project)


def test_two_reporters_of_one_wave_pair_through_the_family(mock_project):
    found = add_parent_mood(mock_project)
    models = invariance.build_models(found.project, found.catalog, found.datasets)
    across = [m for m in models if m.across == invariance.REPORTERS]
    [mood] = [m for m in across if m.instrument_id == "example_mood"]
    assert (mood.wave, mood.reporter) == ("1", "")
    assert list(mood.occasions) == ["child", "parent"]
    child, parent = mood.occasions["child"], mood.occasions["parent"]
    # The same index is the same family in both; a family with two children is taken by child.
    assert set(child.index) & set(parent.index)
    assert any(len(i) == 4 for i in child.index) and "1301C" in child.index
    # The parents gave the children's wave 2 answers, reversed the same way.
    later = next(m for m in models if m.instrument_id == "example_mood" and m.across == "waves")
    families = {i for i in parent.index if len(i) == 4}
    family = next(iter(families & {i[:4] for i in later.occasions["2"].index}))
    assert parent.loc[family].equals(later.occasions["2"].loc[f"{family}C"].rename(family))


GENDER = "item:example_demographics.dem_gender@parent_w1"


def test_groups_come_from_an_item_in_another_file_paired_through_the_family(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    labels = {n: n for n in sample.datasets}
    choices = group_invariance.measure_choices(result, sample.datasets, ["example_mood"], labels)
    assert list(choices) == ["example_mood@child_w1"]
    [mood] = group_invariance.group_models(result, sample, "example_mood@child_w1", GENDER)
    assert mood.across == "example_demographics.dem_gender" and mood.wave == "1"
    gender = analysis.values(result, sample, GENDER)
    options = item_variable(result, GENDER).response_options
    for option in options:
        if option.label in mood.occasions:
            people = mood.occasions[option.label].index
            assert (gender[people] == float(option.value)).all()
    assert sum(len(f) for f in mood.occasions.values()) <= len(sample.people)
    # Two people cannot carry nine items' covariances.
    assert mood.left_out == {"Another gender": 2}


@needs_r
def test_a_multigroup_model_runs_every_step_and_frees_by_group(result):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    [held] = group_invariance.group_models(result, sample, "example_mood@child_w1", GENDER)
    result.project.config.stats.invariance_free = [
        FreedParameter(
            instrument="example_mood", item="ems_3", parameter="loading", across=held.across
        )
    ]
    [freed] = group_invariance.group_models(result, sample, "example_mood@child_w1", GENDER)
    before, after = invariance.fit_models([held, freed], rscript(), "ml")
    assert [s.step for s in before.steps] == ["configural", "metric", "scalar"]
    assert before.problem is None and all(s.problem is None for s in before.steps)
    assert before.steps[1].fit["df"] - after.steps[1].fit["df"] == len(held.occasions) - 1
    scores = invariance.score_tests(held, "scalar", rscript(), "ml")
    assert {s.parameter for s in scores} == {"intercept"} and len(scores) == 9


def run_saved_script(model, estimator: str, folder) -> pd.DataFrame:
    files = invariance.script_files(model, estimator, "EMS")
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")
    measures = invariance.R_STEPS[estimator][1]
    # Read the fit back the way the page reads its own run.
    keep = f'write.csv(t(sapply(fits, lavaan::fitMeasures, c({measures}))), "fits.csv")\n'
    with open(folder / invariance.SCRIPT_FILE, "a", encoding="utf-8") as f:
        f.write(keep)
    done = subprocess.run(
        [rscript(), invariance.SCRIPT_FILE], cwd=folder, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    return pd.read_csv(folder / "fits.csv", index_col=0)


@needs_r
def test_the_saved_script_fits_the_waves_as_the_page_does(result, tmp_path):
    mood = models_of(result)["example_mood"]
    mood.occasions = {wave: mood.occasions[wave] for wave in ("1", "2")}
    [test] = invariance.fit_models([mood], rscript())
    fits = run_saved_script(mood, "wlsmv", tmp_path)
    assert list(fits.index) == [s.step for s in test.steps]
    for step in test.steps:
        assert fits.loc[step.step].iloc[0] == pytest.approx(step.fit["chisq"], rel=1e-6)
        assert fits.loc[step.step].iloc[1] == pytest.approx(step.fit["df"])


@needs_r
def test_the_saved_script_fits_the_groups_with_freed_items_as_the_page_does(result, tmp_path):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], True)
    [held] = group_invariance.group_models(result, sample, "example_mood@child_w1", GENDER)
    result.project.config.stats.invariance_free = [
        FreedParameter(
            instrument="example_mood", item="ems_3", parameter="loading", across=held.across
        )
    ]
    [freed] = group_invariance.group_models(result, sample, "example_mood@child_w1", GENDER)
    [test] = invariance.fit_models([freed], rscript(), "mlr")
    fits = run_saved_script(freed, "mlr", tmp_path)
    for step in test.steps:
        assert fits.loc[step.step].iloc[0] == pytest.approx(step.fit["chisq"], rel=1e-6)
        assert fits.loc[step.step].iloc[1] == pytest.approx(step.fit["df"])
