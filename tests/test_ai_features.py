import subprocess
import sys

import pandas as pd
import pytest

from labcatalog.ai import cleaning, features
from labcatalog.exceptions import EditError
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project

FILES = "nback_trials_w2"


class FakeClient(LLMClient):
    def __init__(self, output: dict) -> None:
        self.output = output
        self.system = self.request = ""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete_structured(self, *, system, user_message, tool_schema):
        self.system, self.request = system, user_message
        return self.output, CallMetadata("fake", "fake-model", 100, 20, 1500)


def example_function(root) -> str:
    # The example's own features(), importing what it uses as the model is asked to.
    text = (root / "scripts" / "extract_nback_w2.py").read_text(encoding="utf-8")
    function = "def features" + text.split("def features", 1)[1].split("\n\n\n", 1)[0] + "\n"
    inside = "    from statistics import NormalDist\n\n    MIN_TRIALS = 30\n"
    return function.replace("-> dict:\n", "-> dict:\n" + inside, 1)


def output(function: str) -> dict:
    item = {"label": "1-back accuracy", "text": "Share of 1-back trials correct", "min": "0"}
    return {
        "function": f"```python\n{function}```",
        "name": "Letter N-back task",
        "construct_name": "Working memory",
        "description": "",
        "items": [
            {"id": "acc_1back", **item, "max": "1"},
            {"id": "no_response", **item, "max": ""},
        ],
        "notes": ["Practice rows are those   with no trials.thisN."],
    }


def test_the_model_sees_one_full_file_the_rule_and_the_measures_wanted(mock_project):
    project = load_project(mock_project)
    sample = features.sample_file(project, FILES)
    assert sample.startswith("raw/nback/ses-2/") and "1306C" not in sample
    request = features.summary_request(project, FILES, sample, "Accuracy and d' per block")
    assert "found by the rule {id}_nback_*_*.csv" in request
    assert f"One person's file: {sample}, 86 rows under its header." in request
    assert "key_resp.keys: 'f', 'j'" in request
    assert request.endswith("The measures wanted:\nAccuracy and d' per block")


def test_a_drafted_summary_runs_and_its_instrument_is_a_draft(mock_project):
    project = load_project(mock_project)
    function = example_function(mock_project)
    client = FakeClient(output(function))
    draft = features.draft_summary(
        project, FILES, "nback_w3", "nback_task", "Accuracy, RT and d'", "python", client
    )
    assert "def features(path: Path) -> dict:" in client.system
    assert draft.script_path == "scripts/extract_nback_w3.py"
    assert draft.step.run == "python scripts/extract_nback_w3.py raw/nback/ses-2 data/nback_w3.csv"
    assert draft.script.startswith("# features() was drafted by fake fake-model on ")
    assert "# - Practice rows are those with no trials.thisN." in draft.script
    assert function in draft.script and "```" not in draft.script
    assert "return {}" not in draft.script
    assert draft.instrument_path == "drafts/nback_task.yaml"
    assert "modality: task" in draft.instrument
    assert "  - {id: acc_1back, label: 1-back accuracy," in draft.instrument
    assert "type: number, min: 0, max: 1}" in draft.instrument
    assert "description" not in draft.instrument

    features.save_summary(mock_project, draft)
    project = load_project(mock_project)
    assert any(s.name == "extract_nback_w3" for s in project.config.prepare)
    assert not [i for i in validate_project(project) if "nback_w3" in i.message]
    ran = subprocess.run(
        [sys.executable, *draft.step.run.split()[1:]],
        cwd=mock_project,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    written = pd.read_csv(mock_project / "data" / "nback_w3.csv", dtype=str)
    same = pd.read_csv(mock_project / "data" / "nback_w2.csv", dtype=str)
    pd.testing.assert_frame_equal(written, same)


def test_a_summary_checks_its_names_before_asking_the_model(mock_project):
    project = load_project(mock_project)
    client = FakeClient({})
    with pytest.raises(EditError, match="instruments/nback.yaml already exists"):
        features.draft_summary(project, FILES, "nback_w3", "nback", "d'", "r", client)
    with pytest.raises(EditError, match="scripts/extract_nback_w2.py already exists"):
        features.draft_summary(project, FILES, "nback_w2", "nback_task", "d'", "python", client)
    with pytest.raises(EditError, match="Say which measures"):
        features.draft_summary(project, FILES, "nback_w3", "nback_task", " ", "r", client)
    assert client.request == ""


def test_a_tab_delimited_utf16_export_is_read(tmp_path):
    # E-DataAid exports E-Prime's data this way.
    (tmp_path / "nback-1001-1.txt").write_text(
        "Subject\tTrial\tStim.ACC\n1001\t1\t1\n1001\t2\t0\n", encoding="utf-16"
    )
    lines = cleaning.raw_lines(tmp_path, "nback-1001-1.txt", cleaning.VALUES)
    assert lines[0] == "Raw file: nback-1001-1.txt, 2 rows under its header."
    assert "Stim.ACC: '1', '0'" in lines
