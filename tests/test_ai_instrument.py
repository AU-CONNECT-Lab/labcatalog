import io

import pytest

from labcatalog.ai import documents
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
        self.images = []

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete_structured(self, *, system, user_message, tool_schema, images=()):
        self.request, self.images = user_message, list(images)
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


def test_an_item_left_on_the_default_set_names_no_set():
    items = [dict(OUTPUT["items"][0], response_set=""), OUTPUT["items"][1]]
    document = ai_instrument.instrument_document("mood", dict(OUTPUT, items=items))
    first, second = document["items"]
    assert "response_set" not in first
    assert second["response_set"] == "agree"


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


def word_file(path):
    # A heading, a table of boxes to tick and the same picture twice, as a survey packet has.
    docx = pytest.importorskip("docx")
    image = pytest.importorskip("PIL.Image")
    picture = io.BytesIO()
    image.new("RGB", (8, 8), "white").save(picture, "PNG")
    document = docx.Document()
    document.add_heading("Mood Form", level=1)
    document.add_paragraph("Mark one box for each feeling.")
    table = document.add_table(rows=2, cols=3)
    shown = [["Feeling", "1 Never", "2 Often"], ["Happy", "☐", "☐"]]
    for row, cells in zip(table.rows, shown, strict=True):
        for cell, text in zip(row.cells, cells, strict=True):
            cell.text = text
    document.add_paragraph("How close are you? Circle one.")
    document.add_picture(io.BytesIO(picture.getvalue()))
    document.add_picture(io.BytesIO(picture.getvalue()))
    document.save(path)
    return path


def test_a_word_file_reads_in_order_with_its_tables_and_numbered_pictures(tmp_path):
    found = documents.read_document(word_file(tmp_path / "packet.docx"))
    assert found.text.splitlines()[:2] == ["# Mood Form", "Mark one box for each feeling."]
    table = ["| Feeling | 1 Never | 2 Often |", "| --- | --- | --- |", "| Happy | ☐ | ☐ |"]
    assert "\n".join(table) in found.text
    # The same picture used twice is one picture.
    assert found.text.count("[picture 1]") == 2 and "[picture 2]" not in found.text
    assert [(n, image.media_type) for n, image in found.pictures] == [(1, "image/png")]
    assert found.unsent == []


def test_a_word_files_pictures_go_to_the_model_unless_turned_off(mock_project, tmp_path):
    path = word_file(tmp_path / "packet.docx")
    client = FakeClient()
    draft = ai_instrument.draft_instrument(mock_project, "mood", path, client, "the mood form")
    assert "Pictures attached, in order: 1." in client.request
    assert len(client.images) == 1 and client.images[0].media_type == "image/png"
    text = draft.path.read_text(encoding="utf-8")
    assert "on " in text and "from packet.docx." in text
    assert text.rstrip().endswith("#   - {key: <its key in references.bib>}")
    ai_instrument.draft_instrument(mock_project, "mood", path, client, pictures=False)
    assert client.images == [] and "Pictures you are not shown: 1." in client.request
