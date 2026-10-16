import pytest

from labcatalog.ai import scoring as ai_scoring
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.pipeline import run_catalog


class FakeClient(LLMClient):
    def __init__(self) -> None:
        self.request = ""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete_structured(self, *, system, user_message, tool_schema):
        self.request = user_message
        output = {
            "r": "d$total_child_w1 <- rowSums(d[items])",
            "python": 'd["total_child_w1"] = d[items].sum(axis=1)',
            "notes": ["The reference lists six items; the catalog has nine."],
        }
        return output, CallMetadata("fake", "fake-model", 100, 20, 1500)


@pytest.fixture
def result(mock_project):
    pytest.importorskip("pymupdf4llm")
    return run_catalog(mock_project)


def test_the_request_holds_the_items_columns_codes_and_reference(result):
    request = ai_scoring.scoring_request(result.project, result.catalog, "example_mood", "child_w1")
    assert "ems_1 | ems_1_w1 | I felt happy. | options 0 = Never" in request
    assert request.count(" | yes") == 3
    assert "Missing codes in this dataset: -99 = refused" in request
    assert "<reference>" in request and "Example Mood Scale" in request


def test_the_scripts_are_saved_with_who_wrote_them_and_the_notes(result):
    client = FakeClient()
    meta = ai_scoring.write_scoring_scripts(
        result.project, result.catalog, "example_mood", "child_w1", client
    )
    assert meta.output_tokens == 20
    paths = ai_scoring.script_paths(result.project, "example_mood", "child_w1")
    r = paths["r"].read_text(encoding="utf-8")
    assert r.startswith("# Example Mood Scale, dataset child_w1: written by fake fake-model")
    assert "# - The reference lists six items; the catalog has nine." in r
    assert r.rstrip().endswith("d$total_child_w1 <- rowSums(d[items])")
    assert "pandas.read_csv()" in paths["python"].read_text(encoding="utf-8")
    assert paths["r"].parent.name == "scoring"
