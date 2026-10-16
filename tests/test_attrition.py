import shutil
from glob import glob

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from labcatalog.gui import attrition as page
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, attrition
from labcatalog.stats import analysis_script as script
from labcatalog.stats.rbridge import ANALYSIS_PACKAGES, r_status

EMS = "example_mood.ems_total"
GENDER = "item:example_demographics.dem_gender"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


needs_r = pytest.mark.skipif(
    rscript() is None or bool(r_status(rscript(), ANALYSIS_PACKAGES).missing),
    reason="R with psych and effectsize is not installed",
)


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def run(result, keys, rscript_path=None):
    found_plan = attrition.plan(result, "mock_study", "1", keys)
    found, engine = script.run_code(
        result, found_plan.sample, found_plan.frame, found_plan.code, rscript_path
    )
    return found_plan, attrition.read(found, found_plan.labels), engine


def test_returned_means_in_any_file_of_the_next_wave(result):
    found_plan = attrition.plan(result, "mock_study", "1", [EMS])
    first_files = attrition.wave_files(result, "mock_study", "1")
    assert {"parent_w1", "child_w1", "eeg_w1", "saliva_w1"} <= set(first_files)
    first = analysis.build_sample(result, first_files, False)
    later = analysis.build_sample(result, attrition.wave_files(result, "mock_study", "2"), False)
    assert found_plan.stayed == len(set(first.people) & set(later.people))
    assert found_plan.stayed + found_plan.left == len(first.people)
    assert found_plan.unit == "family groups"
    assert attrition.plan(result, "mock_study", "3", [EMS]) is None


def test_a_variable_in_two_files_of_the_wave_gets_a_row_each(mock_project):
    # Split child_w1 into two files of wave 1 that both hold the mood scale.
    data = pd.read_csv(mock_project / "data" / "child_w1.csv", dtype=str)
    half = len(data) // 2
    data.iloc[:half].to_csv(mock_project / "data" / "child_w1.csv", index=False)
    data.iloc[half:].to_csv(mock_project / "data" / "child_w1b.csv", index=False)
    shutil.copy(mock_project / "maps" / "child_w1.csv", mock_project / "maps" / "child_w1b.csv")
    config = mock_project / "labcatalog.yaml"
    line = next(x for x in config.read_text().splitlines() if "{name: child_w1," in x)
    extra = line.replace("child_w1", "child_w1b")
    config.write_text(config.read_text().replace(line, f"{line}\n{extra}"))
    study = mock_project / "studies" / "mock_study.yaml"
    study.write_text(study.read_text().replace("[child_w1,", "[child_w1, child_w1b,"))
    found_plan = attrition.plan(run_catalog(mock_project), "mock_study", "1", [EMS])
    first, second = found_plan.labels
    assert first.endswith(" (child_w1)") and second.endswith(" (child_w1b)")
    columns = found_plan.frame[["ems_total_child_w1", "ems_total_child_w1b"]].notna()
    assert columns.all(axis=0).sum() == 0 and columns.any(axis=0).all()
    assert not columns.all(axis=1).any()


def test_python_matches_scipy(result):
    found_plan, compared, engine = run(result, [EMS, GENDER])
    assert engine == script.PYTHON
    frame = found_plan.frame
    ems = next(c for c in found_plan.frame.columns if c.startswith("ems_total"))
    stay = frame.loc[frame[attrition.RETURNED] == 1, ems].dropna()
    left = frame.loc[frame[attrition.RETURNED] == 0, ems].dropna()
    welch = stats.ttest_ind(stay, left, equal_var=False)
    mood = compared[1] if compared[0].label == "Child gender" else compared[0]
    assert (mood.test.statistic, mood.test.p) == pytest.approx((welch.statistic, welch.pvalue))
    d = (stay.mean() - left.mean()) / np.sqrt((stay.var() + left.var()) / 2)
    assert mood.test.effect == pytest.approx(d)
    assert (mood.rows[0].returned_n, mood.rows[0].left_n) == (len(stay), len(left))
    gender = next(c for c in compared if c.label == "Child gender")
    column = next(c for c in frame.columns if c.startswith("dem_gender"))
    table = pd.crosstab(frame[column], frame[attrition.RETURNED])
    chi2, p, dof, _ = stats.chi2_contingency(table, correction=False)
    assert (gender.test.statistic, gender.test.p, gender.test.df) == pytest.approx((chi2, p, dof))
    assert [r.level for r in gender.rows] == ["Girl", "Boy", "Another gender"]


def test_table_and_sentence_read_like_a_paper(result):
    found_plan, compared, _ = run(result, [GENDER, EMS])
    columns, rows = page.attrition_table(found_plan, compared)
    assert [c["label"] for c in columns][1] == f"Returned (n = {found_plan.stayed})"
    assert rows[0]["test"].startswith("χ²(2) = ") and rows[1]["variable"].strip() == "Girl"
    assert rows[-1]["test"].startswith("t(") and "(" in rows[-1]["returned"]
    text = page.sentence(found_plan, compared)
    everyone = found_plan.stayed + found_plan.left
    assert text.startswith(f"Of the {everyone} family groups at Wave 1, {found_plan.left} (")
    assert "did not take part at Wave 2." in text and "differ" in text


@needs_r
def test_r_and_python_agree(result):
    _, in_python, _ = run(result, [EMS, GENDER])
    _, in_r, engine = run(result, [EMS, GENDER], rscript())
    assert engine == script.R
    for a, b in zip(in_r, in_python, strict=True):
        assert a.label == b.label
        assert (a.test.statistic, a.test.df, a.test.p) == pytest.approx(
            (b.test.statistic, b.test.df, b.test.p)
        )
        assert a.test.small == b.test.small
        if a.test.effect is not None:
            assert a.test.effect == pytest.approx(b.test.effect)
        for x, y in zip(a.rows, b.rows, strict=True):
            assert (x.level, x.returned_n, x.left_n) == (y.level, y.returned_n, y.left_n)


def test_student_follows_the_project_setting(result):
    result.project.config.stats.t_test = "student"
    found_plan, compared, _ = run(result, [EMS])
    assert "Student's t test" in found_plan.code.r and "var.equal = TRUE" in found_plan.code.r
    frame = found_plan.frame
    ems = next(c for c in frame.columns if c.startswith("ems_total"))
    stay = frame.loc[frame[attrition.RETURNED] == 1, ems].dropna()
    left = frame.loc[frame[attrition.RETURNED] == 0, ems].dropna()
    student = stats.ttest_ind(stay, left, equal_var=True)
    [mood] = compared
    assert (mood.test.statistic, mood.test.p) == pytest.approx((student.statistic, student.pvalue))
    assert mood.test.df == len(stay) + len(left) - 2
    assert page.statistic(mood.test).startswith(f"t({len(stay) + len(left) - 2}) = ")
