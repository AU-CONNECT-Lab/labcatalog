import shutil
from glob import glob

import pytest

from labcatalog.pipeline import run_catalog
from labcatalog.reports import results
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats.analysis_script import MissingData

SCORES = ["example_parent_stress.eps_mean", "example_child_sleep.ecs_total"]


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


def missing_in(result, rscript_path):
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], False)
    data = script.AnalysisData(result, sample)
    variables = [data.variable(f"{k}@parent_w1") for k in SCORES]
    frame = data.frame()
    found, _ = script.run_code(result, sample, frame, script.missing_code(variables), rscript_path)
    return frame, variables, script.read_missing(found, [v.column for v in variables])


def test_each_variable_and_each_pattern_counts_the_people_in_the_sample(result):
    frame, variables, missing = missing_in(result, None)
    columns = [v.column for v in variables]
    assert missing.people == len(frame)
    for column, n, lacking in missing.counts:
        assert (n, lacking) == (frame[column].notna().sum(), frame[column].isna().sum())
    assert missing.complete == frame[columns].notna().all(axis=1).sum()
    assert [people for _, people in missing.patterns] == sorted(
        (people for _, people in missing.patterns), reverse=True
    )
    assert sum(people for present, people in missing.patterns if not present[1]) == next(
        lacking for column, _, lacking in missing.counts if column == columns[1]
    )


@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_r_and_python_give_the_same_counts_and_patterns(result):
    assert missing_in(result, rscript())[2] == missing_in(result, None)[2]


def test_the_paragraph_gives_the_complete_share_and_the_range():
    missing = MissingData(
        [("a", 9, 1), ("b", 7, 3)], [((True, True), 6), ((True, False), 3), ((False, True), 1)]
    )
    assert results.missing_text(missing, ["A", "B"]) == (
        "Of the 10 people, 6 (60.0%) had values on all 2 variables. Missing values ranged from "
        "1 (10.0%) for A to 3 (30.0%) for B."
    )
    whole = MissingData([("a", 4, 0)], [((True,), 4)])
    assert results.missing_text(whole, ["A"]) == "All 4 people had values on the variable."
