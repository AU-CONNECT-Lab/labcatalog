import pytest

from labcatalog import ai_measures
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.project import load_project


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
            "description": "It asks how often\n  the respondent felt low.",
            "notes": ["The reference lists six items; the catalog has nine."],
        }
        return output, CallMetadata("fake", "fake-model", 100, 20, 1500)


@pytest.fixture
def project(mock_project):
    pytest.importorskip("pymupdf4llm")
    return load_project(mock_project)


def test_the_request_holds_the_construct_items_and_reference(project):
    request = ai_measures.description_request(project, "example_mood")
    assert request.startswith("Instrument: Example Mood Scale (EMS)")
    assert "Construct: Mood and negative affect" in request
    assert "ems_1 | I felt happy. | options 0 = Never" in request
    assert "<reference>" in request and "Example Mood Scale" in request


def test_the_draft_comes_back_on_one_line_with_the_notes(project):
    client = FakeClient()
    draft = ai_measures.draft_description(project, "example_mood", client)
    assert draft.description == "It asks how often the respondent felt low."
    assert draft.notes == ["The reference lists six items; the catalog has nine."]
    assert draft.meta.model == "fake-model"
    assert client.request.startswith("Instrument:")
