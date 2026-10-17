import pytest

from labcatalog.ai import instrument as ai_instrument
from labcatalog.exceptions import EditError
from labcatalog.issues import Issue
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.metadata import editing
from labcatalog.metadata.validate import check_instrument
from labcatalog.project import load_model
from labcatalog.schema import Instrument

OUTPUT = {
    "name": "Example Mood Scale",
    "abbreviation": "",
    "construct_name": "Mood",
    "instructions": "Think about the past two weeks.",
    "response_sets": [
        {
            "id": "frequency",
            "options": [{"value": "0", "label": "Never"}, {"value": "1", "label": "Often"}],
        },
        {
            "id": "agree",
            "options": [{"value": "1", "label": "Disagree"}, {"value": "2", "label": "Agree"}],
        },
    ],
    "default_response_set": "frequency",
    "items": [
        {
            "id": "ems_1",
            "text": "I felt happy.",
            "type": "choice",
            "response_set": "frequency",
            "min": "",
            "max": "",
            "reverse": True,
        },
        {
            "id": "ems_2",
            "text": "I felt sad.",
            "type": "choice",
            "response_set": "agree",
            "min": "",
            "max": "",
            "reverse": False,
        },
        {
            "id": "ems_3",
            "text": "Hours of sleep",
            "type": "number",
            "response_set": "",
            "min": "0",
            "max": "24",
            "reverse": False,
        },
    ],
    "scores": [
        {
            "id": "ems_total",
            "label": "Total",
            "method": "sum",
            "items": ["ems_1", "ems_2"],
            "missing_rule": "prorate",
            "min_valid": "1",
        },
    ],
    "notes": ["The PDF does not say\nhow to treat missing answers."],
}


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
        return OUTPUT, CallMetadata("fake", "fake-model", 100, 20, 1500)


@pytest.fixture
def pdf(mock_project):
    pytest.importorskip("pymupdf4llm")
    return mock_project / "references" / "example_mood.pdf"


def test_the_draft_is_a_valid_instrument_with_the_notes_on_top(mock_project, pdf):
    client = FakeClient()
    draft = ai_instrument.draft_instrument(mock_project, "mood", pdf, client)
    assert client.request.startswith("Instrument ID: mood")
    assert "<document>" in client.request and "Example Mood Scale" in client.request
    assert draft.path == mock_project / "drafts" / "mood.yaml"
    text = draft.path.read_text(encoding="utf-8")
    assert "# - The PDF does not say how to treat missing answers." in text
    assert text.endswith("#   - {key: <its key in references.bib>, pdf: example_mood.pdf}\n")
    assert editing.check_text("drafts/mood.yaml", text) == []
    issues: list[Issue] = []
    instrument = load_model(draft.path, Instrument, mock_project, issues)
    assert issues == [] and check_instrument(instrument, "drafts/mood.yaml") == []
    assert instrument.abbreviation is None
    assert instrument.response_sets[0].options[1].value == 1
    first, second, hours = instrument.items
    assert first.response_set is None and first.reverse
    assert second.response_set == "agree"
    assert (hours.type, hours.min, hours.max) == ("number", 0, 24)
    assert instrument.scores[0].missing_rule == "prorate" and instrument.scores[0].min_valid == 1


def test_the_lab_can_name_which_instrument_of_the_pdf_to_draft(mock_project, pdf):
    client = FakeClient()
    ai_instrument.draft_instrument(mock_project, "mood", pdf, client)
    assert "Instrument to draft" not in client.request
    ai_instrument.draft_instrument(mock_project, "mood", pdf, client, " the short form ")
    assert client.request.startswith("Instrument ID: mood\nInstrument to draft: the short form\n")


def test_an_id_already_in_instruments_is_refused_before_asking_the_model(mock_project, pdf):
    client = FakeClient()
    with pytest.raises(EditError, match="already exists"):
        ai_instrument.draft_instrument(mock_project, "example_mood", pdf, client)
    assert client.request == ""
