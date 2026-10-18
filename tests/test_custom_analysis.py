import shutil
from glob import glob

import pandas as pd
import pytest

from labcatalog.ai import custom as ai
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.pipeline import run_catalog
from labcatalog.processes import end_tree
from labcatalog.stats import analysis, custom
from labcatalog.stats import analysis_script as script

CHILD = "child_w1"
TOTAL = f"example_worries_temper.ewt_total@{CHILD}"


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


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


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


@pytest.fixture
def sample(result):
    return analysis.build_sample(result, [CHILD], True)


def group_key(result) -> str:
    return next(iter(script.group_choices(result, [CHILD], {CHILD: CHILD})))


def test_the_model_sees_each_column_with_its_values_and_count_but_no_rows(result, sample):
    keys = [TOTAL, group_key(result)]
    frame, variables, _ = custom.analysis_frame(result, sample, keys)
    text = custom.columns_text(result, sample, frame, variables)
    total = variables[0]
    assert total.items and all(column in frame for column in total.items)
    count = int(frame[total.column].notna().sum())
    assert (
        f"{total.column} | the score {total.label} ({CHILD}), the sum of its items | number | {count}"
        in text
    )
    assert f"{total.items[0]} | an item of {total.label}, reversed where the scale says so" in text
    group = variables[1]
    assert (
        f"{group.column} | " in text and f"{group.options[0][0]:g} = {group.options[0][1]}" in text
    )
    assert f"in_{CHILD} | 1 if the person is in the dataset {CHILD}, else 0" in text
    assert f"{len(frame)} rows, one for each person" in text
    person = str(frame.iloc[0, 0])
    assert person not in text


def test_a_draft_and_a_fix_send_the_columns_the_request_and_the_error(result, sample):
    client = FakeClient(
        {
            "script": "  d <- read.csv('analysis_data.csv')\n",
            "changes": [],
            "notes": ["Which test?"],
        }
    )
    found = ai.draft_analysis("COLUMNS", "Compare the groups", "r", script.DATA_FILE, client)
    assert "one R script" in client.system and "analysis_data.csv" in client.system
    assert client.request == "COLUMNS\n\nThe analysis wanted:\nCompare the groups"
    assert found.script == "d <- read.csv('analysis_data.csv')\n" and found.notes == ["Which test?"]
    client.output = {"script": "x <- 1\ny <- 3\n", "changes": ["Fixed y"], "notes": []}
    error = "start " + "x" * ai.SHOWN_OUTPUT + " Error: object 'z' not found"
    fixed = ai.fix_analysis(
        "COLUMNS", "Compare", "python", "data.csv", "x <- 1\ny <- 2\n", error, client
    )
    assert "Python script" in client.system
    assert "<script>\nx <- 1\ny <- 2\n\n</script>" in client.request
    assert "Error: object 'z' not found" in client.request and "start" not in client.request
    assert "-y <- 2\n+y <- 3" in fixed.diff() and fixed.changes == ["Fixed y"]


def test_a_python_script_runs_beside_the_data_and_gives_back_what_it_wrote(result, sample):
    frame, variables, _ = custom.analysis_frame(result, sample, [TOTAL])
    column = variables[0].column
    code = (
        "import pandas as pd\n"
        "d = pd.read_csv('analysis_data.csv')\n"
        f"print('mean', round(d['{column}'].mean(), 3))\n"
        f"d[['{column}']].describe().to_csv('summary.csv')\n"
    )
    ran = custom.run_script("python", code, frame, None)
    assert ran.ok
    assert ran.output == f"mean {round(frame[column].mean(), 3)}"
    assert list(ran.files) == ["summary.csv"]
    broken = custom.run_script(
        "python", "print('before')\nraise ValueError('no such column')\n", frame, None
    )
    assert not broken.ok
    assert broken.output.startswith("before\n") and "ValueError: no such column" in broken.output


def test_a_running_script_can_be_stopped():
    started = []
    code = "import time\nprint('started', flush=True)\ntime.sleep(60)\n"

    def stop(process) -> None:
        started.append(process)
        end_tree(process)

    ran = custom.run_script("python", code, pd.DataFrame({"x": [1]}), None, stop)
    assert started and not ran.ok


def test_an_r_script_needs_rscript(result, sample):
    with pytest.raises(Exception, match="set the path to Rscript"):
        custom.run_script("r", "print(1)", pd.DataFrame({"x": [1]}), None)


@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_an_r_script_runs_in_r():
    frame = pd.DataFrame({"x": [1.0, 2.0, 4.0]})
    code = "d <- read.csv('analysis_data.csv')\ncat('mean', mean(d$x), '\\n')\nwrite.csv(d, 'out.csv')\n"
    ran = custom.run_script("r", code, frame, rscript())
    assert ran.ok and ran.output == "mean 2.333333" and list(ran.files) == ["out.csv"]
