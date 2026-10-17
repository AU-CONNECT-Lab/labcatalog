from labcatalog.ai import interpret as ai_interpret
from labcatalog.llm import CallMetadata, LLMClient
from labcatalog.reports.tables import PaperTable

SHOWN = PaperTable(
    "Correlations Among Variables",
    [{"name": "variable", "label": "Variable"}, {"name": "c0", "label": "1"}],
    [{"variable": "1. Mood", "c0": "—"}, {"variable": "2. Sleep", "c0": "-.34***"}],
    "Pearson r.",
)
PARAGRAPH = "Sleep was negatively correlated with Mood, r(118) = -.34, p < .001."


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
            "interpretation": "Children who slept worse\n  reported lower mood.",
            "notes": ["One correlation; the design is cross-sectional."],
        }
        return output, CallMetadata("fake", "fake-model", 100, 20, 1500)


def test_the_request_holds_only_the_tables_and_the_paragraph():
    request = ai_interpret.interpretation_request([SHOWN], PARAGRAPH)
    assert request.startswith("Table X\nCorrelations Among Variables\nVariable\t1")
    assert "2. Sleep\t-.34***" in request and "Note. Pearson r." in request
    assert request.endswith(f"Results paragraph: {PARAGRAPH}")


def test_the_interpretation_comes_back_on_one_line_with_the_notes():
    client = FakeClient()
    found = ai_interpret.interpret([SHOWN], PARAGRAPH, client)
    assert found.text == "Children who slept worse reported lower mood."
    assert found.notes == ["One correlation; the design is cross-sectional."]
    assert found.meta.model == "fake-model"
    assert PARAGRAPH in client.request
