import shutil
import subprocess
from glob import glob

import numpy as np
import pandas as pd
import pytest

from labcatalog.codegen import output_name, score_code_python, score_code_r
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project
from labcatalog.resolve import ResolvedScore, resolve_catalog
from labcatalog.scoring import compute_score
from labcatalog.sources import load_datasets

RULES = [(rule, method) for rule in ["complete", "prorate", "zero"] for method in ["sum", "mean"]]


def rscript() -> str | None:
    found = shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )
    return found


@pytest.fixture
def mock(mock_project):
    project = load_project(mock_project)
    catalog = resolve_catalog(project)
    return mock_project, catalog, load_datasets(project)


def variants(catalog) -> list[ResolvedScore]:
    ems = next(s for s in catalog.scores if s.key == "example_mood.ems_total@child_w1")
    eps = next(s for s in catalog.scores if s.key == "example_parent_stress.eps_mean@parent_w1")
    mixed = eps.model_copy(
        update={
            "key": "mixed@parent_w1",
            "score_id": "mixed",
            "columns": ["eps_1_w1", "ecs_1_w1", "ecs_2_w1"],
            "reverse_columns": ["ecs_1_w1"],
            "reverse_bounds": {"ecs_1_w1": (0.0, 2.0)},
            "valid_values": {
                "eps_1_w1": [1.0, 2.0, 3.0, 4.0, 5.0],
                "ecs_1_w1": [0.0, 1.0, 2.0],
                "ecs_2_w1": [0.0, 1.0, 2.0],
            },
            "missing_rule": "prorate",
            "min_valid": 2,
        }
    )
    scores = [
        base.model_copy(update={"missing_rule": rule, "method": method, "min_valid": 4})
        for base in (ems, eps)
        for rule, method in RULES
    ]
    return [*scores, mixed]


def expected(datasets, score) -> np.ndarray:
    return compute_score(datasets[score.dataset], score).to_numpy(dtype=float)


def test_generated_python_matches_labcatalog(mock):
    root, catalog, datasets = mock
    for score in variants(catalog):
        d = pd.read_csv(root / "data" / f"{score.dataset}.csv")
        exec(score_code_python(score), {"d": d})
        got = d[output_name(score)].to_numpy(dtype=float)
        np.testing.assert_allclose(got, expected(datasets, score), err_msg=score.key)


@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_generated_r_matches_labcatalog(mock, tmp_path):
    root, catalog, datasets = mock
    scores = variants(catalog)
    parts = []
    for n, score in enumerate(scores):
        data = (root / "data" / f"{score.dataset}.csv").as_posix()
        out = (tmp_path / f"out{n}.csv").as_posix()
        parts.append(
            f'd <- read.csv("{data}")\n{score_code_r(score)}\n'
            f'write.csv(d["{output_name(score)}"], "{out}", row.names = FALSE)'
        )
    script = tmp_path / "check.R"
    script.write_text("\n".join(parts), encoding="utf-8")
    subprocess.run([rscript(), str(script)], check=True, capture_output=True)
    for n, score in enumerate(scores):
        got = pd.read_csv(tmp_path / f"out{n}.csv").iloc[:, 0].to_numpy(dtype=float)
        np.testing.assert_allclose(got, expected(datasets, score), err_msg=score.key)


def test_unavailable_items_explain_why(mock):
    _, catalog, _ = mock
    score = catalog.scores[0].model_copy(update={"unavailable_items": ["x"]})
    assert "cannot be computed" in score_code_r(score)
    assert "cannot be computed" in score_code_python(score)


def test_python_label_code_labels_items_and_blanks_missing_codes(mock_project):
    result = run_catalog(mock_project)
    d = pd.read_csv(mock_project / "data" / "parent_w1.csv")
    names = {"d": d}
    exec(result.label_snippets["parent_w1"]["python"], names)
    assert names["column_labels"]["dem_edu_w1"] == (
        "What is the highest level of education you have completed?"
    )
    assert names["variable_value_labels"]["eps_1_w1"][1] == "Strongly disagree"
    assert names["variable_value_labels"]["eps_1_w1"][-99] == "refused"
    assert names["variable_value_labels"]["dem_age_w1"] == names["missing_codes"]
    assert "dem_comment_w1" not in names["variable_value_labels"]
    labelled = list(names["missing_ranges"])
    assert d[labelled].isin([-99, -98, -97]).any().any()
    assert not names["d"][labelled].isin([-99, -98, -97]).any().any()


@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_r_label_code_gives_haven_what_it_needs_to_save_a_sav(mock_project, tmp_path):
    result = run_catalog(mock_project)
    parts = []
    for name, snippet in result.label_snippets.items():
        data = (mock_project / "data" / f"{name}.csv").as_posix()
        out = (tmp_path / f"{name}.sav").as_posix()
        parts.append(f'd <- read.csv("{data}")\n{snippet["r"]}\nwrite_sav(d, "{out}")')
    saved = (tmp_path / "parent_w1.sav").as_posix()
    report = (tmp_path / "report.txt").as_posix()
    parts.append(
        f'b <- read_sav("{saved}", user_na = TRUE)\n'
        'writeLines(c(attr(b$eps_1_w1, "label"), names(attr(b$eps_1_w1, "labels")), '
        f'format(attr(b$eps_1_w1, "na_values")), attr(b$dem_comment_w1, "label")), "{report}")'
    )
    script = tmp_path / "labels.R"
    script.write_text("\n".join(parts), encoding="utf-8")
    subprocess.run([rscript(), str(script)], check=True, capture_output=True)
    assert (tmp_path / "report.txt").read_text(encoding="utf-8").splitlines() == [
        "I feel overwhelmed by my responsibilities as a parent.",
        "Strongly disagree",
        "Disagree",
        "Neutral",
        "Agree",
        "Strongly agree",
        "refused",
        "not applicable",
        "don't know",
        "-99",
        "-98",
        "-97",
        "Is there anything else about your family's situation you would like us to know?",
    ]
