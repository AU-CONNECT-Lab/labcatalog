import shutil
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def demo_project(tmp_path: Path) -> Path:
    root = tmp_path / "demo"
    shutil.copytree(EXAMPLES / "demo", root)
    return root


@pytest.fixture
def mock_project(tmp_path: Path) -> Path:
    root = tmp_path / "mock_study"
    shutil.copytree(EXAMPLES / "mock_study", root)
    return root
