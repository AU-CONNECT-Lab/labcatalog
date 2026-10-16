import shutil
from glob import glob

import pandas as pd
import pytest

from labcatalog import invariance
from labcatalog.cfa import SUBSCALES
from labcatalog.pipeline import run_catalog
from labcatalog.rbridge import CFA_PACKAGES, r_status
from labcatalog.scoring import score_items


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
    assert set(models) == {"example_mood", "example_parent_stress", "example_child_sleep"}
    mood = models["example_mood"]
    assert (mood.study, mood.reporter, mood.kind) == ("mock_study", "child", SUBSCALES)
    assert list(mood.factors) == ["ems_sadness", "ems_worry", "ems_low_positive"]
    assert list(mood.waves) == ["1", "2", "3"]


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
    expected = expected[sorted(expected.columns, key=list(mood.waves["1"].columns).index)]
    assert mood.waves["1"].equals(expected)
    assert set(mood.waves["1"].columns) == {f"ems_{i}" for i in range(1, 10)}


def test_r_names_in_messages_become_items_and_waves(result, tmp_path):
    mood = models_of(result)["example_mood"]
    _, original = invariance.write_model(tmp_path, 1, mood)
    first = list(mood.waves["3"].columns)[0]
    message = "categories differ: x1_t1, x1_t3; factor f2_t2"
    assert invariance.readable(message, original) == (
        f"categories differ: {first} (wave 1), {first} (wave 3); factor ems_worry (wave 2)"
    )
    data = pd.read_csv(tmp_path / "m1.csv")
    assert len(data) == len(set().union(*(set(f.index) for f in mood.waves.values())))


@needs_r
def test_steps_add_constraints_and_compare_with_the_step_before(result):
    mood = models_of(result)["example_mood"]
    mood.waves = {wave: mood.waves[wave] for wave in ("1", "2")}
    [test] = invariance.fit_models([mood], rscript())
    assert test.problem is None
    assert test.n == {"1": len(mood.waves["1"]), "2": len(mood.waves["2"])}
    assert [s.step for s in test.steps] == list(invariance.STEPS)
    assert all(s.problem is None for s in test.steps)
    dfs = [s.fit["df"] for s in test.steps]
    assert dfs == sorted(dfs) and dfs[0] < dfs[-1]
    assert test.steps[0].chisq_diff is None
    assert all(s.df_diff > 0 and 0 <= s.p_diff <= 1 for s in test.steps[1:])


def test_an_option_nobody_chose_in_one_wave_stops_the_model_before_r(result):
    stress = models_of(result)["example_parent_stress"]
    stress.waves["3"]["eps_1"] = stress.waves["3"]["eps_1"].replace(5.0, 4.0)
    [test] = invariance.fit_models([stress], "C:/no/such/Rscript.exe")
    assert test.steps == []
    assert test.n == {wave: len(frame) for wave, frame in stress.waves.items()}
    assert "eps_1 in wave 3 (5)" in test.problem
    shifted = {"1": pd.DataFrame({"a": [1.0, 2.0]}), "2": pd.DataFrame({"a": [2.0, 3.0]})}
    stress.waves = shifted
    assert "a in wave 1 (3); a in wave 2 (1)" in invariance.unchosen_options(stress)
