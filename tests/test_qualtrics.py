import json
from pathlib import Path

import pytest

from labcatalog.codebook import qualtrics
from labcatalog.codebook.core import (
    INSTRUMENTS,
    ITEMS,
    codebook_paths,
    import_codebook,
    write_templates,
)
from labcatalog.exceptions import CodebookError
from labcatalog.project import init_project, load_project

CONFIG = """\
project: {name: Pilot}
vocab: {reporters: [self]}
studies:
  pilot: {waves: {1: {}}}
datasets:
  - {name: pilot_w1, modality: questionnaire, study: pilot, wave: 1, reporter: self, source: csv, path: data/pilot_w1.csv}
"""
DATA = """\
id,Q29_1,Q29_2,Q2,Q2_4_TEXT,Q5_1,Q5_3,Q7,Q8_1,Q9,Q9_DO_1
A1,1,3,10,,1,,moved,55,2,1
A2,2,1,40,dog,,1,,10,1,2
"""


def question(qid: str, tag: str, kind: str, selector: str | None = None, **rest) -> dict:
    payload = {"QuestionID": qid, "DataExportTag": tag, "QuestionType": kind, "Selector": selector}
    return {"Element": "SQ", "PrimaryAttribute": qid, "Payload": payload | rest}


def choices(*labels: str, typed: str | None = None) -> dict:
    found = {str(i): {"Display": label} for i, label in enumerate(labels, start=1)}
    if typed:
        found[typed]["TextEntry"] = "true"
    return found


SURVEY = {
    "SurveyEntry": {"SurveyName": "Pilot"},
    "SurveyElements": [
        {
            "Element": "BL",
            "Payload": [
                {"Type": "Default", "Description": "Intro", "BlockElements": [
                    {"Type": "Question", "QuestionID": "QID1"}]},
                {"Type": "Trash", "Description": "Trash / Unused Questions", "BlockElements": [
                    {"Type": "Question", "QuestionID": "QID90"}]},
                {"Type": "Standard", "Description": "Child Mood", "BlockElements": [
                    {"Type": "Question", "QuestionID": "QID36"}, {"Type": "Page Break"}]},
                {"Type": "Standard", "Description": "Background", "BlockElements": [
                    {"Type": "Question", "QuestionID": f"QID{n}"} for n in (2, 5, 7, 8, 9, 10)]},
            ],
        },
        question("QID1", "Q1", "DB", "TB", QuestionText="<b>Welcome</b>"),
        question("QID90", "Q2", "TE", "SL", QuestionText="Old question"),
        question(
            "QID36", "Q29", "Matrix", "Likert", SubSelector="SingleAnswer",
            QuestionText="<span>How often did you feel&nbsp;this way?</span>",
            Choices=choices("Sad", "Happy; calm"), ChoiceOrder=[1, 2],
            Answers=choices("Never", "Sometimes", "Often"), AnswerOrder=[1, 2, 3],
            ChoiceDataExportTags=False,
        ),
        question(
            "QID2", "Q2", "MC", "SAVR", QuestionText="Which pet do you have?",
            Choices=choices("Cat", "Dog", "None", "Other", typed="4"), ChoiceOrder=["1", "2", "3", "4"],
            RecodeValues={"1": "10", "2": "20", "3": "30", "4": "40"},
        ),
        question(
            "QID5", "Q5", "MC", "MAVR", QuestionText="Which do you use?",
            Choices=choices("Phone", "Tablet", "Laptop"), ChoiceOrder=[1, 2, 3],
        ),
        question("QID7", "Q7", "TE", "ML", QuestionText="Anything else?"),
        question(
            "QID8", "Q8", "Slider", "HSLIDER", QuestionText="How much pain?",
            Choices=choices("Today"), ChoiceOrder=[1],
            Configuration={"CSSliderMin": 0, "CSSliderMax": 100},
        ),
        question("QID9", "Q9", "MC", "SAVR", QuestionText="First", Choices=choices("Yes", "No")),
        question("QID10", "Q9", "MC", "SAVR", QuestionText="Second", Choices=choices("Yes", "No")),
    ],
}  # fmt: skip


@pytest.fixture
def survey(tmp_path: Path) -> Path:
    path = tmp_path / "pilot.qsf"
    path.write_text(json.dumps(SURVEY), encoding="utf-8")
    return path


def test_columns_follow_qualtrics_export_names(survey):
    fields = qualtrics.read_survey(survey)
    assert list(fields) == [
        "Q29_1",
        "Q29_2",
        "Q2",
        "Q2_4_TEXT",
        "Q2_40_TEXT",
        "Q2_TEXT",
        "Q5_1",
        "Q5_2",
        "Q5_3",
        "Q7",
        "Q8_1",
    ]
    sad = fields["Q29_1"]
    assert (sad.form, sad.form_label, sad.text) == ("child_mood", "Child Mood", "Sad")
    assert sad.choices == "1=Never; 2=Sometimes; 3=Often"
    assert fields["Q29_2"].text == "Happy, calm"
    assert fields["Q2"].choices == "10=Cat; 20=Dog; 30=None; 40=Other"
    assert (fields["Q2_4_TEXT"].type, fields["Q2_4_TEXT"].text) == ("text", "Other (typed answer)")
    assert (fields["Q5_3"].text, fields["Q5_3"].choices) == (
        "Which do you use?: Laptop",
        "1=Selected",
    )
    assert (fields["Q7"].type, fields["Q8_1"].type, fields["Q8_1"].max) == ("text", "number", "100")


def test_a_survey_file_fills_in_items_and_imports(tmp_path, survey):
    root = init_project(tmp_path / "pilot", example=False)
    (root / "labcatalog.yaml").write_text(CONFIG, encoding="utf-8")
    (root / "data" / "pilot_w1.csv").write_text(DATA, encoding="utf-8")
    project = load_project(root)
    write_templates(project, "pilot_w1", survey)
    paths = codebook_paths(project, "pilot_w1")
    rows = paths[ITEMS].read_text(encoding="utf-8-sig").splitlines()
    assert rows[1:4] == [
        "id,,,,,,,,",
        "Q29_1,child_mood,q29_1,Sad,choice,1=Never; 2=Sometimes; 3=Often,,,",
        'Q29_2,child_mood,q29_2,"Happy, calm",choice,1=Never; 2=Sometimes; 3=Often,,,',
    ]
    # Two questions share Q9, so a person decides which one the column holds.
    assert rows[-2:] == ["Q9,,,,,,,,", "Q9_DO_1,,,,,,,,"]
    assert paths[INSTRUMENTS].read_text(encoding="utf-8-sig").splitlines()[1:] == [
        "child_mood,Child Mood,,,,",
        "background,Background,,,,",
    ]
    assert import_codebook(project, "pilot_w1").issues == []
    mood = (root / "instruments" / "child_mood.yaml").read_text(encoding="utf-8")
    assert "name: Child Mood" in mood


def test_other_files_are_not_surveys(tmp_path):
    path = tmp_path / "other.qsf"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(CodebookError, match="not a Qualtrics survey file"):
        qualtrics.read_survey(path)
