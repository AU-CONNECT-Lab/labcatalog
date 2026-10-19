import pandas as pd
import pytest

from labcatalog.exceptions import EditError
from labcatalog.metadata import changes, new_instrument
from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project

LINES = """I go to bed at the same time each night.

I use a screen in bed. (R)
I wake up rested.
"""


def add_columns(root, dataset, columns):
    path = root / "data" / f"{dataset}.csv"
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for n, column in enumerate(columns):
        frame[column] = [str((row + n) % 4) for row in range(len(frame))]
    frame.to_csv(path, index=False)


def test_a_new_instrument_is_written_mapped_and_given(mock_project):
    add_columns(mock_project, "child_w1", ["shq_1_w1", "shq_2_w1", "shq_3_w1"])
    project = load_project(mock_project)
    draft = new_instrument.Draft("sleep_habits")
    draft.about |= {"name": "Sleep Habits Questionnaire", "abbreviation": "SHQ"}
    new_instrument.check_about(project, draft)
    draft.options = new_instrument.copy_options(project, "example_mood")
    draft.default_set = "frequency"
    draft.items = new_instrument.items_from_lines(draft, LINES)
    assert [(r["id"], r["reverse"]) for r in draft.items] == [
        ("shq_1", False),
        ("shq_2", True),
        ("shq_3", False),
    ]
    assert draft.items[1]["text"] == "I use a screen in bed."
    draft.scores = [new_instrument.suggest_total(draft)]
    items = [r["id"] for r in draft.items]
    draft.given = {"child_w1": new_instrument.guess_columns(project, "child_w1", items)}
    assert draft.given["child_w1"] == {
        "shq_1": "shq_1_w1",
        "shq_2": "shq_2_w1",
        "shq_3": "shq_3_w1",
    }

    found = new_instrument.changes(project, draft)
    assert changes.check(project, found) == []
    changes.write(project, found)

    text = (mock_project / "instruments" / "sleep_habits.yaml").read_text(encoding="utf-8")
    assert "modality" not in text and "demographics" not in text
    assert "  - {id: shq_2, text: I use a screen in bed., reverse: true}" in text
    assert "default_response_set: frequency" in text
    assert text.index("name:") < text.index("response_sets:") < text.index("items:")
    assert (
        (mock_project / "maps" / "child_w1.csv")
        .read_text(encoding="utf-8")
        .endswith("shq_3_w1,sleep_habits,shq_3\n")
    )
    study = (mock_project / "studies" / "mock_study.yaml").read_text(encoding="utf-8")
    assert "- {instrument: sleep_habits, datasets: [child_w1]}" in study
    reloaded = load_project(mock_project)
    assert reloaded.instruments["sleep_habits"].items[1].reverse
    assert validate_project(reloaded) == validate_project(project)
    result = run_catalog(mock_project)
    assert result.scores["child_w1"]["sleep_habits.shq_total@child_w1"].notna().all()


def test_an_untouched_instrument_is_written_back_as_it_was(mock_project):
    project = load_project(mock_project)
    for instrument_id in project.instruments:
        draft = new_instrument.existing(project, instrument_id)
        change = new_instrument.instrument_change(project, draft)
        assert change.text == change.opened.text, instrument_id


def test_completing_an_instrument_changes_only_what_was_filled_in(mock_project):
    project = load_project(mock_project)
    assert new_instrument.first_gap(project, "example_screen_time") == "about"
    draft = new_instrument.existing(project, "example_screen_time")
    before = new_instrument.instrument_change(project, draft).opened.text.splitlines()
    draft.about["description"] = "It asks how many hours a day the child spends on screens."
    draft.about["license"] = "Free for research use"
    draft.references = ["example2019"]
    change = new_instrument.instrument_change(project, draft)
    after = change.text.splitlines()
    assert [line for line in after if line not in before] == [
        "description: It asks how many hours a day the child spends on screens.",
        "references:",
        "  - {key: example2019}",
        "license: Free for research use",
    ]
    assert [line for line in before if line not in after] == []
    assert changes.check(project, [change]) == []


def test_completing_an_instrument_can_give_a_reference_its_pdf(mock_project):
    project = load_project(mock_project)
    draft = new_instrument.existing(project, "example_screen_time")
    draft.references = ["example2019"]
    draft.pdfs = {"example2019": "example_mood.pdf"}
    change = new_instrument.instrument_change(project, draft)
    assert "  - {key: example2019, pdf: example_mood.pdf}" in change.text.splitlines()
    assert changes.check(project, [change]) == []
    changes.write(project, [change])

    draft = new_instrument.existing(load_project(mock_project), "example_screen_time")
    assert draft.pdfs == {"example2019": "example_mood.pdf"}
    draft.pdfs = {}
    change = new_instrument.instrument_change(project, draft)
    assert "  - {key: example2019}" in change.text.splitlines()


def test_a_new_instrument_needs_a_free_id_and_a_name(mock_project):
    project = load_project(mock_project)
    with pytest.raises(EditError, match="already exists"):
        new_instrument.check_about(project, new_instrument.Draft("example_mood"))
    with pytest.raises(EditError, match="Name"):
        new_instrument.check_about(project, new_instrument.Draft("new_one"))


def test_pasted_items_continue_after_the_ones_there(mock_project):
    draft = new_instrument.Draft("habits")
    draft.items = [{"id": "habits_1", "text": "One"}, {"id": "habits_3", "text": "Three"}]
    found = new_instrument.items_from_lines(draft, "Four\nFive (r)\n")
    assert [(r["id"], r["text"], r["reverse"]) for r in found] == [
        ("habits_4", "Four", False),
        ("habits_5", "Five", True),
    ]
