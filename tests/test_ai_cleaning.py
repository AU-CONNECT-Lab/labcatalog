import pytest

from labcatalog.ai import cleaning
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project

RAW = "raw/parent_w1_export.csv"


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


def test_the_model_sees_each_raw_columns_values_or_the_first_rows_and_the_clean_columns(result):
    project, catalog = result.project, result.catalog
    request = cleaning.draft_request(project, catalog, "parent_w1", RAW, cleaning.VALUES)
    assert "Raw file: raw/parent_w1_export.csv, 196 rows under its header." in request
    assert "Finished: 'Finished', '{\"ImportId\": \"finished\"}', 'True', 'False'" in request
    assert "pid | the ID of the person the row is about |" in request
    assert "visit_date | the date, written %Y-%m-%d |" in request
    assert (
        "eps_1_w1 | Example Parenting Stress Scale, eps_1: I feel overwhelmed by my "
        "responsibilities as a parent. | options 1 = Strongly disagree" in request
    )
    assert "Missing codes: -99 = refused" in request
    assert "<raw>" not in request
    rows = cleaning.draft_request(project, catalog, "parent_w1", RAW, cleaning.ROWS)
    lines = rows.split("<raw>\n")[1].split("\n</raw>")[0].splitlines()
    assert len(lines) == cleaning.RAW_ROWS + 1 and lines[0].startswith("StartDate,EndDate")


def test_a_drafted_script_becomes_a_step_that_writes_a_new_file(result):
    client = FakeClient({"script": "d <- read.csv(args[1])", "changes": [], "notes": ["Kept"]})
    draft = cleaning.draft_script(result.project, result.catalog, "parent_w1", RAW, "r", client)
    assert "Rscript script.R <raw> <clean>" in client.system
    assert draft.script_path == "scripts/clean_parent_w1.R"
    assert draft.script.startswith("# Cleans raw/parent_w1_export.csv into data/parent_w1.csv")
    assert "# - Kept\n\nd <- read.csv(args[1])\n" in draft.script
    root = result.project.root
    before = len(result.project.config.prepare)
    cleaning.save_draft(root, draft)
    assert (root / draft.script_path).read_text(encoding="utf-8") == draft.script
    # The example's step of the same name is replaced, in its place.
    project = load_project(root)
    steps = project.config.prepare
    assert len(steps) == before and steps[0] == draft.step
    assert steps[0].run == f"Rscript scripts/clean_parent_w1.R {RAW} data/parent_w1.csv"
    assert "{name: clean_parent_w1, run: Rscript" in (root / "labcatalog.yaml").read_text()
    assert not [i for i in validate_project(project) if i.location == "labcatalog.yaml"]


def test_a_fix_revises_the_script_that_writes_the_file_with_the_problem(result):
    [issue] = [i for i in result.report.issues if i.code == "id_whitespace"]
    rows = [{"row": "31", "id": "' 1031P'"}]
    step = cleaning.cleaning_step(result.project, "parent_w1")
    assert cleaning.script_of(step) == "scripts/clean_export.py"
    root = result.project.root
    old = (root / "scripts/clean_export.py").read_text(encoding="utf-8")
    revised = old.replace('r["pid"], r["StartDate"]', 'r["pid"].strip(), r["StartDate"]')
    client = FakeClient({"script": revised, "changes": ["Strip spaces"], "notes": []})
    draft = cleaning.fix_script(result.project, result.catalog, issue, rows, client)
    assert "<script>\n" + old in client.request
    assert f"Problem: {issue.message}" in client.request
    assert "row 31, id ' 1031P'" in client.request
    assert "Python script" in client.system
    assert draft.step is None and draft.changes == ["Strip spaces"]
    assert '+        writer.writerow([r["pid"].strip()' in draft.diff()
    config = (root / "labcatalog.yaml").read_text(encoding="utf-8")
    cleaning.save_draft(root, draft)
    assert (root / "scripts/clean_export.py").read_text(encoding="utf-8") == revised
    assert (root / "labcatalog.yaml").read_text(encoding="utf-8") == config
