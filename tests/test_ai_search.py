from labcatalog.ai import search as ai_search
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.metadata.browse import build_index, counts, matches
from labcatalog.project import load_project


class FakeClient(LLMClient):
    def __init__(self, found: list[dict]) -> None:
        self.found = found
        self.request = ""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return "fake-model"

    def complete_structured(self, *, system, user_message, tool_schema):
        self.request = user_message
        return {"matches": self.found}, CallMetadata("fake", "fake-model", 900, 40, 2000)


def test_the_request_lists_each_instrument_and_its_items(mock_project):
    project = load_project(mock_project)
    text = ai_search.catalog_text(project)
    assert "Instrument example_mood: Example Mood Scale (EMS)" in text
    assert "Construct: Mood and negative affect" in text
    assert "ems_1 | I felt happy." in text
    assert "Labels: " in text and "sleep" in text


def test_matches_naming_unknown_items_are_dropped(mock_project):
    project = load_project(mock_project)
    client = FakeClient(
        [
            {"instrument": "example_mood", "item": "ems_1", "reason": "Asks about\n mood."},
            {"instrument": "example_child_sleep", "item": "", "reason": "All about sleep."},
            {"instrument": "example_mood", "item": "ems_99", "reason": "Made up."},
            {"instrument": "nope", "item": "", "reason": "Made up."},
        ]
    )
    found = ai_search.search_catalog(project, "feeling down", client)
    assert client.request.startswith("Request: feeling down\n\nCatalog:\nInstrument ")
    assert [(m.instrument_id, m.item_id, m.reason) for m in found.matches] == [
        ("example_mood", "ems_1", "Asks about mood."),
        ("example_child_sleep", None, "All about sleep."),
    ]
    assert found.dropped == 2
    assert found.instruments == {"example_mood", "example_child_sleep"}


def test_the_found_instruments_narrow_the_list_and_the_counts(mock_project):
    index = build_index(load_project(mock_project))
    only = {"example_mood"}
    assert list(matches(index, {}, only=only)) == ["example_mood"]
    reporters = counts(index, {}, only=only)["reporter"]
    assert reporters == {"parent": 0, "child": 1}
