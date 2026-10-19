import shutil
from glob import glob
from pathlib import Path

import pytest

from labcatalog.metadata import changes, studies
from labcatalog.project import EXAMPLE_DIR, load_project

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


@pytest.fixture
def demo_project(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    shutil.copytree(EXAMPLES / "demo", root)
    return root


SECOND_STUDY = "mock_study_2"


@pytest.fixture
def example_project(tmp_path: Path) -> Path:
    root = tmp_path / "example"
    shutil.copytree(EXAMPLE_DIR, root)
    return root


@pytest.fixture
def mock_project(tmp_path: Path) -> Path:
    # The example's first study alone, which most tests count on; example_project has both.
    root = tmp_path / "mock_study"
    shutil.copytree(EXAMPLE_DIR, root)
    project = load_project(root)
    changes.write(project, studies.delete_study(project, SECOND_STUDY))
    for path in [
        *(root / "data").glob("s2_*.csv"),
        root / "data" / f"participants_{SECOND_STUDY}.csv",
    ]:
        path.unlink()
    (root / "instruments" / "sleep_watch.yaml").unlink()
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace(", actigraphy]", "]"), encoding="utf-8")
    return root


@pytest.fixture
def pilot_project(mock_project: Path) -> Path:
    # A second study whose IDs repeat the first's: its own roster, and child_w1's file and map.
    root = mock_project
    (root / "data" / "pilot_roster.csv").write_text(
        "pid,family_id,role,birth_year,gender\n1001C,9001,child,2017,1\n1001P,9001,parent,1980,2\n",
        encoding="utf-8",
    )
    shutil.copy(root / "maps" / "roster_mock_study.csv", root / "maps" / "roster_pilot.csv")
    (root / "studies" / "pilot.yaml").write_text(
        "study: pilot\nadministrations:\n"
        "  - {instrument: example_mood, datasets: [pilot_w1], target: self}\n"
        "  - {instrument: example_worries_temper, datasets: [pilot_w1], target: self}\n",
        encoding="utf-8",
    )
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    text = text.replace(
        "\n# One entry per data file",
        "  pilot:\n    waves: {1: {}}\n    roster: {path: data/pilot_roster.csv, id_column: pid, "
        "group_column: family_id, role_column: role, instrument: example_participants}\n"
        "\n# One entry per data file",
    ).replace(
        "datasets:\n",
        "datasets:\n  - {name: pilot_w1, modality: questionnaire, study: pilot, wave: 1, "
        "reporter: child, source: csv, path: data/child_w1.csv, map: child_w1}\n",
    )
    config.write_text(text, encoding="utf-8")
    return root
