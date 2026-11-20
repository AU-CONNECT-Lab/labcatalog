import pytest
from conftest import rscript

from labcatalog import pipeline
from labcatalog.ai import scoring as ai_scoring
from labcatalog.config import dataset_by_name
from labcatalog.exceptions import EditError, LLMError
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
    assert "ID column: pid" in request
    assert "ems_total | Total score | sum of ems_1, ems_2" in request
    assert "<reference>" in request and "Example Mood Scale" in request
    assert "several waves" not in request


def test_a_pdf_that_cannot_be_read_says_why(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf\n" * 20)
    with pytest.raises(LLMError, match="broken.pdf cannot be read as a PDF"):
        ai_scoring.pdf_text(broken)
    locked = tmp_path / "locked.pdf"
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Item 1. I feel sad.")
    document.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    with pytest.raises(LLMError, match="locked.pdf needs a password"):
        ai_scoring.pdf_text(locked)


def test_a_folder_dataset_is_refused_before_the_model_is_asked(result):
    client = FakeClient()
    with pytest.raises(EditError, match="nback_trials_w2 reads a folder"):
        ai_scoring.write_scoring_scripts(
            result.project, result.catalog, "example_mood", "nback_trials_w2", client
        )
    assert client.request == ""


def test_one_wave_of_a_long_file_asks_for_that_waves_rows(result):
    dataset_by_name(result.project.config, "child_w1").wave_column = "wave"
    request = ai_scoring.scoring_request(result.project, result.catalog, "example_mood", "child_w1")
    assert "this dataset is its rows with wave 1, so score only those rows" in request


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
    assert (
        "# python scoring/example_mood_child_w1.py data/child_w1.csv "
        "data/child_w1_example_mood_scores.csv" in paths["python"].read_text(encoding="utf-8")
    )
    assert paths["r"].parent.name == "scoring"


class UnclosedClient(FakeClient):
    def complete_structured(self, **kwargs):
        output, meta = super().complete_structured(**kwargs)
        return {**output, "python": "total = (1,"}, meta


def test_a_written_script_that_does_not_parse_is_reported(result, monkeypatch):
    monkeypatch.setattr(pipeline, "make_llm_client", lambda *_: UnclosedClient())
    meta, unparsed = pipeline.run_scoring_script(
        result, "example_mood", "child_w1", "fake", "", "", rscript()
    )
    assert meta.output_tokens == 20
    assert list(unparsed) == ["Python"]
    assert "'(' was never closed" in unparsed["Python"]
