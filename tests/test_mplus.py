import pytest

from labcatalog.exceptions import MplusError
from labcatalog.pipeline import run_catalog
from labcatalog.stats import mplus
from labcatalog.stats.cfa import SECOND_ORDER, SUBSCALE_SCORES, SUBSCALES, build_models


@pytest.fixture
def mood(mock_project):
    result = run_catalog(mock_project)
    models = build_models(result.project, result.catalog, result.datasets)
    return [m for m in models if (m.instrument_id, m.dataset) == ("example_mood", "child_w1")]


def test_each_model_gets_an_input_and_its_data(mood):
    files = mplus.cfa_files(mood, "wlsmv", "Example Mood Scale: EMS")
    assert len(files) == 2 * len(mood)
    kinds = [m.kind for m in mood]
    subscales = files[f"mplus_cfa_{kinds.index(SUBSCALES) + 1}.inp"]
    assert "  CATEGORICAL = x1-x9;" in subscales and "  ESTIMATOR = WLSMV;" in subscales
    assert "  f1 BY x1* x2 x3;" in subscales and "  f1 f2 f3@1;" in subscales
    assert "Example Mood Scale, EMS, child_w1" in subscales
    second = files[f"mplus_cfa_{kinds.index(SECOND_ORDER) + 1}.inp"]
    assert "  g BY f1* f2 f3;" in second and "  g@1;" in second
    n = kinds.index(SUBSCALE_SCORES) + 1
    scores = files[f"mplus_cfa_{n}.inp"]
    assert "CATEGORICAL" not in scores and "  ESTIMATOR = ML;" in scores
    assert "! x2 = ems_worry" in scores
    rows = files[f"mplus_cfa_{n}.dat"].splitlines()
    assert len(rows) == len(mood[kinds.index(SUBSCALE_SCORES)].data)
    assert all(len(row.split()) == 3 for row in rows)
    assert all(len(line) <= 90 for text in files.values() for line in text.splitlines())


def test_ml_items_are_continuous(mood):
    text = mplus.cfa_input(mood[0], "data.dat", "ml", "EMS")
    assert "CATEGORICAL" not in text and "  ESTIMATOR = ML;" in text


def test_run_writes_an_output_beside_each_input(tmp_path):
    fake = tmp_path / "mplus.bat"
    fake.write_text("@copy %1 %2 >nul\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / "a.inp").write_text("TITLE: a\n", encoding="utf-8")
    assert mplus.run(str(fake), work) == [work / "a.out"]
    with pytest.raises(MplusError, match="Mplus not found"):
        mplus.run(str(tmp_path / "missing.exe"), work)
