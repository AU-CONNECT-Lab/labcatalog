import shutil
import sys
from glob import glob

import pandas as pd
import pytest

from labcatalog.ai import custom as ai
from labcatalog.config import SavedAnalysis
from labcatalog.gui import preferences
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.metadata import editing
from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.processes import end_tree
from labcatalog.project import load_project
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
    ran = custom.run_script("python", code, frame, sys.executable)
    assert ran.ok
    assert ran.output == f"mean {round(frame[column].mean(), 3)}"
    assert list(ran.files) == ["summary.csv"]
    broken = custom.run_script(
        "python", "print('before')\nraise ValueError('no such column')\n", frame, sys.executable
    )
    assert not broken.ok
    assert broken.output.startswith("before\n") and "ValueError: no such column" in broken.output


def test_a_running_script_can_be_stopped():
    started = []
    code = "import time\nprint('started', flush=True)\ntime.sleep(60)\n"

    def stop(process) -> None:
        started.append(process)
        end_tree(process)

    ran = custom.run_script("python", code, pd.DataFrame({"x": [1]}), sys.executable, stop)
    assert started and not ran.ok


def test_r_and_python_scripts_need_their_program(monkeypatch, tmp_path):
    with pytest.raises(Exception, match="set the path to Rscript"):
        custom.run_script("r", "print(1)", pd.DataFrame({"x": [1]}), None)
    with pytest.raises(Exception, match="set the path to Python"):
        custom.run_script("python", "print(1)", pd.DataFrame({"x": [1]}), None)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert preferences.python() == sys.executable
    assert preferences.step_python() is None
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert preferences.python() == preferences.step_python() == sys.executable
    preferences.save({preferences.PYTHON: "C:/Python/python.exe"})
    assert preferences.python() == "C:/Python/python.exe"


def test_the_python_check_gives_the_version_and_the_packages_it_lacks(monkeypatch):
    found = custom.python_status(sys.executable)
    assert found.version == sys.version.split()[0]
    monkeypatch.setattr(custom, "PYTHON_PACKAGES", ("pandas", "no_such_package_here"))
    assert custom.python_status(sys.executable).missing == ["no_such_package_here"]


@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_an_r_script_runs_in_r():
    frame = pd.DataFrame({"x": [1.0, 2.0, 4.0]})
    code = "d <- read.csv('analysis_data.csv')\ncat('mean', mean(d$x), '\\n')\nwrite.csv(d, 'out.csv')\n"
    ran = custom.run_script("r", code, frame, rscript())
    assert ran.ok and ran.output == "mean 2.333333" and list(ran.files) == ["out.csv"]


def test_an_analysis_kept_in_the_project_is_its_script_and_an_entry_and_can_be_removed(
    result, sample
):
    root = result.project.root
    kept = SavedAnalysis(
        name="ewt_groups",
        script="analyses/ewt_groups.R",
        datasets=[CHILD],
        variables=[TOTAL],
        request="Compare the groups",
    )
    editing.save_analysis(root, kept, "print(1)\n")
    assert (root / kept.script).read_text(encoding="utf-8") == "print(1)\n"
    project = load_project(root)
    assert project.config.analyses == [kept]
    assert not [i for i in validate_project(project) if i.location == "labcatalog.yaml"]
    replaced = kept.model_copy(update={"every_dataset": False})
    editing.save_analysis(root, replaced, "print(2)\n")
    assert load_project(root).config.analyses == [replaced]
    editing.remove_analysis(root, replaced)
    assert not (root / kept.script).exists()
    assert "analyses" not in (root / "labcatalog.yaml").read_text(encoding="utf-8")


def test_a_kept_analysis_names_datasets_and_a_script_that_exist(result):
    root = result.project.root
    for name in ("one", "one"):
        editing.save_analysis(
            root, SavedAnalysis(name=name, script=f"analyses/{name}.R", datasets=["nope"]), ""
        )
    project = load_project(root)
    project.config.analyses.append(project.config.analyses[0])
    (root / "analyses/one.R").unlink()
    issues = [i for i in validate_project(project) if "analyses" in i.message]
    found = {i.code: i for i in reversed(issues)}
    assert found["unknown_reference"].details["path"] == ["analyses", 0, "datasets", 0]
    assert "file not found: analyses/one.R" in found["invalid_value"].message
    assert found["duplicate_id"].details["value"] == "one"


def test_mplus_gets_short_names_numbers_for_ids_and_the_start_of_the_input(result, sample):
    names = custom.short_names(["family", "ems_total_child_w1", "ems_total_child_w2", "1st", "a.b"])
    assert names == {
        "family": "family",
        "ems_total_child_w1": "ems_tota",
        "ems_total_child_w2": "ems_tot2",
        "1st": "v1st",
        "a.b": "a_b",
    }
    frame, variables, _ = custom.analysis_frame(result, sample, [TOTAL])
    data = custom.mplus_data(frame)
    assert all(pd.api.types.is_numeric_dtype(data[c]) for c in data.columns)
    assert data.iloc[:, 0].nunique() == frame.iloc[:, 0].nunique()
    start = custom.mplus_start(frame, "A two-factor model\nof worries and temper")
    lines = start.splitlines()
    assert lines[0] == "TITLE: A two-factor model of worries and temper"
    assert "DATA: FILE = analysis_data.dat;" in lines and "  MISSING = ALL (-999);" in lines
    assert all(len(line) <= 80 for line in lines)
    short = custom.short_names(list(frame.columns))
    assert f"! {short[variables[0].column]} = {variables[0].column}" in lines
    text = custom.columns_text(result, sample, frame, variables, custom.MPLUS)
    assert text.startswith("analysis_data.dat:")
    assert f"{short[variables[0].column]} ({variables[0].column}) | the score" in text
    assert "a number for each ID" in text
    files = custom.data_files(custom.MPLUS, frame)
    assert list(files) == ["analysis_data.dat"] and "-999" in files["analysis_data.dat"]


def test_an_mplus_draft_follows_the_start_or_is_empty_when_mplus_does_not_fit():
    client = FakeClient({"script": "MODEL: f BY x1-x3;", "changes": [], "notes": []})
    found = ai.draft_analysis("COLUMNS", "A CFA", "mplus", "d.dat", client, "TITLE: t\n")
    assert "Write Mplus only for the models it is for" in client.system
    assert "The start of the input:\n<input>\nTITLE: t\n</input>" in client.request
    assert found.script == "TITLE: t\nMODEL: f BY x1-x3;\n"
    client.output = {"script": "", "changes": [], "notes": ["Use R for a t test."]}
    declined = ai.draft_analysis("COLUMNS", "A t test", "mplus", "d.dat", client, "TITLE: t\n")
    assert declined.script == "" and declined.notes == ["Use R for a t test."]
    with pytest.raises(Exception, match="set the path to Mplus"):
        custom.run_script("mplus", "TITLE: t", pd.DataFrame({"x": [1]}), None)
