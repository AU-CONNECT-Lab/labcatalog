import shutil
from glob import glob
from pathlib import Path

import numpy as np
import pandas as pd
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


# Four times of the mood scale in wave 2: before and after each of two interactions.
VISIT = [
    ("mood_pre_parent", "before", "parent"),
    ("mood_post_parent", "after", "parent"),
    ("mood_pre_peer", "before", "peer"),
    ("mood_post_peer", "after", "peer"),
]
CHILD_W2 = (
    "  - {name: child_w2, modality: questionnaire, study: mock_study, wave: 2, reporter: child, "
    "source: csv, path: data/child_w2.csv, date_column: visit_date, snapshot_date: 2026-10-10}\n"
)
MOOD = "  - {instrument: example_mood, datasets: [child_w1, child_w2, child_w3], target: self}"


@pytest.fixture
def visit_project(mock_project: Path) -> Path:
    root = mock_project
    child = pd.read_csv(root / "data" / "child_w2.csv", dtype=str, keep_default_na=False)
    rng = np.random.default_rng(5)
    frame = pd.DataFrame({"pid": child["pid"]})
    lines = []
    for name, time, interaction in VISIT:
        worse = name == "mood_post_parent"
        for i in range(1, 10):
            base = pd.to_numeric(child[f"ems_{i}_w2"], errors="coerce")
            base = base.where(base >= 0)
            moved = base + rng.integers(-1, 2, len(child)) + worse * (rng.random(len(child)) < 0.6)
            frame[f"ems_{i}_{name}"] = moved.clip(0, 3).astype("Int64")
        rows = [f"ems_{i}_{name},example_mood,ems_{i}" for i in range(1, 10)]
        (root / "maps" / f"{name}.csv").write_text(
            "column,instrument,item\npid,,\n" + "\n".join(rows) + "\n", encoding="utf-8"
        )
        lines.append(
            f"  - {{name: {name}, modality: questionnaire, study: mock_study, wave: 2, "
            f"reporter: child, source: csv, path: data/mood_visit_w2.csv, "
            f"occasion: {{time: {time}, interaction: {interaction}}}}}\n"
        )
    frame.to_csv(root / "data" / "mood_visit_w2.csv", index=False)
    config = root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace(CHILD_W2, CHILD_W2 + "".join(lines)), encoding="utf-8")
    study = root / "studies" / "mock_study.yaml"
    names = ", ".join(name for name, _, _ in VISIT)
    text = study.read_text(encoding="utf-8")
    study.write_text(text.replace(MOOD, MOOD.replace("child_w3]", f"child_w3, {names}]")))
    return root
