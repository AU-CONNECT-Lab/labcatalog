import shutil
import subprocess
from glob import glob

import numpy as np
import pandas as pd
import pytest

from labcatalog.codegen import output_name, score_code_python, score_code_r
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
