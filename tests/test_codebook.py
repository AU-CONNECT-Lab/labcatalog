import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

from labcatalog.cli import main
from labcatalog.codebook import redcap, spss
from labcatalog.codebook.core import (
    INSTRUMENTS,
    ITEMS,
    SCORES,
    ai_prompt,
    codebook_paths,
    import_codebook,
    split_ai_answer,
    unmapped_datasets,
    write_templates,
)
from labcatalog.exceptions import CodebookError
from labcatalog.pipeline import run_catalog, run_check
from labcatalog.project import init_project, load_project

CONFIG = """\
project: {name: Pilot}
vocab: {reporters: [self]}
studies:
  pilot: {waves: {1: {}}}
datasets:
  - {name: pilot_w1, modality: questionnaire, study: pilot, wave: 1, reporter: self, source: csv, path: data/pilot_w1.csv, date_column: date}
"""
DATA = """\
id,date,anx1,anx2,anx3,anx_total,age,remarks
A1,2026-01-05,0,2,1,1,30,moved house
A2,2026-01-06,1,,2,4.5,41,
"""
FILLED = {
    ITEMS: """\
column,instrument,item,text,type,choices,reverse,min,max
id,,,,,,,,
date,,,,,,,,
anx1,anx,anx_1,I feel nervous.,,0=Never; 1=Sometimes; 2=Often,,,
anx2,anx,anx_2,I feel calm.,,0=Never; 1=Sometimes; 2=Often,yes,,
anx3,anx,anx_3,I worry about many things.,,0=Never; 1=Sometimes; 2=Often,,,
anx_total,anx,score:anx_total,,,,,,
age,background,age,How old are you?,number,,,18,99
remarks,background,remarks,Anything else?,text,,,,
""",
    INSTRUMENTS: """\
instrument,name,abbreviation,kind,construct
anx,Pilot Anxiety Scale,PAS,,Anxiety
background,Background,,demographics,
""",
    SCORES: """\
instrument,score,label,method,items,missing_rule,min_valid
anx,anx_total,Total,sum,anx_1-anx_3,prorate,2
""",
}


@pytest.fixture
def pilot(tmp_path: Path) -> Path:
    root = init_project(tmp_path / "pilot", example=False)
    (root / "labcatalog.yaml").write_text(CONFIG, encoding="utf-8")
    (root / "data" / "pilot_w1.csv").write_text(DATA, encoding="utf-8")
    return root


def fill(root: Path, **changes: tuple[str, str]) -> None:
    for name, path in codebook_paths(load_project(root), "pilot_w1").items():
        text = FILLED[name]
        for key, (old, new) in changes.items():
            if key.startswith(name.removesuffix(".csv")):
                assert old in text
                text = text.replace(old, new)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8-sig")


def test_templates_guess_instruments_from_column_prefixes(pilot):
    project = load_project(pilot)
    assert unmapped_datasets(project) == ["pilot_w1"]
    write_templates(project, "pilot_w1")
    paths = codebook_paths(project, "pilot_w1")
    assert paths[ITEMS].read_bytes().startswith(b"\xef\xbb\xbf")
    assert paths[ITEMS].read_text(encoding="utf-8-sig").splitlines() == [
        "column,instrument,item,text,type,choices,reverse,min,max",
        "id,,,,,,,,",
        "date,,,,,,,,",
        "anx1,anx,anx1,,,,,,",
        "anx2,anx,anx2,,,,,,",
        "anx3,anx,anx3,,,,,,",
        "anx_total,anx,anx_total,,,,,,",
        "age,,,,,,,,",
        "remarks,,,,text,,,,",
    ]
    assert paths[INSTRUMENTS].read_text(encoding="utf-8-sig").splitlines()[1:] == ["anx,,,,"]
    assert paths[SCORES].read_text(encoding="utf-8-sig").splitlines()[1:] == []
    with pytest.raises(CodebookError, match="already has codebook files"):
        write_templates(project, "pilot_w1")


def test_import_writes_instruments_and_map_that_score_like_the_data(pilot):
    fill(pilot)
    result = import_codebook(load_project(pilot), "pilot_w1")
    assert result.issues == []
    assert [p.relative_to(pilot).as_posix() for p in result.written] == [
        "instruments/anx.yaml",
        "instruments/background.yaml",
        "maps/pilot_w1.csv",
    ]
    assert (pilot / "instruments" / "anx.yaml").read_text(encoding="utf-8") == (
        "# yaml-language-server: $schema=../schemas/instrument.schema.json\n"
        "id: anx\n"
        "name: Pilot Anxiety Scale\n"
        "abbreviation: PAS\n"
        "construct_name: Anxiety\n"
        "response_sets:\n"
        "  - id: set_1\n"
        "    options:\n"
        "      - {value: 0, label: Never}\n"
        "      - {value: 1, label: Sometimes}\n"
        "      - {value: 2, label: Often}\n"
        "default_response_set: set_1\n"
        "items:\n"
        "  - {id: anx_1, text: I feel nervous.}\n"
        "  - {id: anx_2, text: I feel calm., reverse: true}\n"
        "  - {id: anx_3, text: I worry about many things.}\n"
        "scores:\n"
        "  - {id: anx_total, label: Total, method: sum, items: [anx_1, anx_2, anx_3], missing_rule: prorate, min_valid: 2}\n"
    )
    assert (pilot / "maps" / "pilot_w1.csv").read_text(encoding="utf-8").splitlines() == [
        "column,instrument,item",
        "id,,",
        "date,,",
        "anx1,anx,anx_1",
        "anx2,anx,anx_2",
        "anx3,anx,anx_3",
        "anx_total,anx,score:anx_total",
        "age,background,age",
        "remarks,background,remarks",
    ]
    assert result.reused == []
    [(instruction, lines)] = result.steps
    assert instruction == "Create studies/pilot.yaml with:"
    (pilot / "studies" / "pilot.yaml").write_text(lines + "\n", encoding="utf-8")
    assert run_check(pilot).issues == []
    catalog = run_catalog(pilot)
    assert catalog.scores["pilot_w1"]["anx.anx_total@pilot_w1"].tolist() == [1.0, 4.5]
    assert catalog.project.instruments["background"].kind == "demographics"


def test_import_reports_each_problem_by_file_and_line(pilot):
    fill(
        pilot,
        items_choices=(
            "anx1,anx,anx_1,I feel nervous.,,0=Never; 1=Sometimes; 2=Often",
            "anx1,anx,anx_1,I feel nervous.,,",
        ),
        items_type=(
            "age,background,age,How old are you?,number",
            "age,background,age,How old are you?,numbr",
        ),
        items_reverse=("Anything else?,text,,,", "Anything else?,text,,maybe,"),
        scores_range=("anx_1-anx_3", "anx_1-anx_9"),
    )
    result = import_codebook(load_project(pilot), "pilot_w1")
    assert [(i.level, i.location, i.message) for i in result.issues] == [
        (
            "error",
            "codebook/pilot_w1/items.csv:4",
            "a choice item needs choices (or type number or text)",
        ),
        ("error", "codebook/pilot_w1/items.csv:8", "type must be one of choice, number, text"),
        ("error", "codebook/pilot_w1/items.csv:8", "min and max apply to number items only"),
        ("error", "codebook/pilot_w1/items.csv:9", "reverse must be yes or no, not maybe"),
        ("error", "codebook/pilot_w1/scores.csv:2", "items: anx_1-anx_9 is not an item of anx"),
    ]
    assert not (pilot / "maps" / "pilot_w1.csv").exists()
    assert not (pilot / "instruments" / "anx.yaml").exists()


def test_import_needs_utf8(pilot):
    fill(pilot)
    path = codebook_paths(load_project(pilot), "pilot_w1")[ITEMS]
    path.write_text(FILLED[ITEMS].replace("I worry", "I’m worried"), encoding="cp1252")
    [issue] = import_codebook(load_project(pilot), "pilot_w1").issues
    assert issue.location == "codebook/pilot_w1/items.csv"
    assert "CSV UTF-8" in issue.message


def test_ai_answer_is_split_into_the_three_files(pilot):
    project = load_project(pilot)
    write_templates(project, "pilot_w1")
    scores = "```csv\n" + FILLED[SCORES] + "```\n\n"
    rest = (
        "```\n" + FILLED[ITEMS] + "```\n\nAnd the instruments:\n"
        "```csv\n" + FILLED[INSTRUMENTS] + "```\n"
    )
    split_ai_answer(project, "pilot_w1", "Here are the files.\n\n" + scores + rest)
    for name, path in codebook_paths(project, "pilot_w1").items():
        assert path.read_text(encoding="utf-8-sig") == FILLED[name]
    assert import_codebook(project, "pilot_w1").issues == []
    with pytest.raises(CodebookError, match="no code block for scores.csv;"):
        split_ai_answer(project, "pilot_w1", rest)


def test_prompt_holds_column_names_but_no_data(pilot):
    project = load_project(pilot)
    write_templates(project, "pilot_w1")
    prompt = ai_prompt(project, "pilot_w1")
    assert "pilot_w1 (study pilot, wave 1, reporter self)" in prompt
    assert "anx_total,anx,anx_total" in prompt
    assert "missing_rule: complete" in prompt
    assert "2026-01-05" not in prompt
    assert "moved house" not in prompt


REDCAP_HEADER = [
    "Variable / Field Name",
    "Form Name",
    "Section Header",
    "Field Type",
    "Field Label",
    "Choices, Calculations, OR Slider Labels",
    "Field Note",
    "Text Validation Type OR Show Slider Number",
    "Text Validation Min",
    "Text Validation Max",
    "Identifier?",
]
REDCAP_FIELDS = [
    ["id", "background", "", "text", "Record ID", "", "", "", "", "", ""],
    ["intro", "mood_scale", "", "descriptive", "<b>Please answer</b>", "", "", "", "", "", ""],
    ["mood_1", "mood_scale", "", "radio", "<p>I feel <i>sad</i></p>", "0, Never | 1, Sometimes; often | 2, Always", "", "", "", "", ""],
    ["mood_10", "mood_scale", "", "dropdown", "I feel tired &amp; slow", "0, Never | 1, Sometimes | 2, Always", "", "", "", "", ""],
    ["mood_total", "mood_scale", "", "calc", "Total", "[mood_1]+[mood_10]", "", "", "", "", ""],
    ["race", "background", "", "checkbox", "Race", "1, White | 2, Black or African American", "", "", "", "", "y"],
    ["smoker", "background", "", "yesno", "Do you smoke?", "", "", "", "", "", ""],
    ["age", "background", "", "text", "Age", "", "", "integer", "18", "99", ""],
    ["pain", "background", "", "slider", "Pain today", "Low | Middle | High", "", "", "", "", ""],
    ["remarks", "background", "", "notes", "Anything else?", "", "", "", "", "", ""],
]  # fmt: skip
REDCAP_DATA = """\
id,date,mood_1_w1,mood_10_w1,mood_total,race___1,race___2,smoker,age,pain,remarks,background_complete,redcap_event_name
A1,2026-01-05,0,2,2,1,0,1,30,55,moved,2,baseline_arm_1
A2,2026-01-06,1,1,2,0,1,0,41,10,,2,baseline_arm_1
"""


def write_dictionary(path: Path, header: list[str]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(REDCAP_FIELDS)
    return path


def test_a_redcap_dictionary_fills_in_items_and_imports(pilot, tmp_path):
    (pilot / "data" / "pilot_w1.csv").write_text(REDCAP_DATA, encoding="utf-8")
    dictionary = write_dictionary(tmp_path / "dictionary.csv", REDCAP_HEADER)
    project = load_project(pilot)
    write_templates(project, "pilot_w1", dictionary)
    paths = codebook_paths(project, "pilot_w1")
    assert paths[ITEMS].read_text(encoding="utf-8-sig").splitlines() == [
        "column,instrument,item,text,type,choices,reverse,min,max",
        "id,,,,,,,,",
        "date,,,,,,,,",
        'mood_1_w1,mood_scale,mood_1,I feel sad,choice,"0=Never; 1=Sometimes, often; 2=Always",,,',
        "mood_10_w1,mood_scale,mood_10,I feel tired & slow,choice,0=Never; 1=Sometimes; 2=Always,,,",
        "mood_total,,,,,,,,",
        "race___1,background,race___1,Race: White,choice,0=Unchecked; 1=Checked,,,",
        "race___2,background,race___2,Race: Black or African American,choice,"
        "0=Unchecked; 1=Checked,,,",
        "smoker,background,smoker,Do you smoke?,choice,1=Yes; 0=No,,,",
        "age,background,age,Age,number,,,18,99",
        "pain,background,pain,Pain today,number,,,0,100",
        "remarks,background,remarks,Anything else?,text,,,,",
        "background_complete,,,,,,,,",
        "redcap_event_name,,,,text,,,,",
    ]
    assert paths[INSTRUMENTS].read_text(encoding="utf-8-sig").splitlines()[1:] == [
        "mood_scale,Mood scale,,,",
        "background,Background,,,",
    ]
    result = import_codebook(project, "pilot_w1")
    assert result.issues == []
    mood = (pilot / "instruments" / "mood_scale.yaml").read_text(encoding="utf-8")
    assert "{value: 1, label: 'Sometimes, often'}" in mood


def test_an_spss_file_fills_in_wording_options_and_types(pilot, tmp_path):
    pyreadstat = pytest.importorskip("pyreadstat")
    frame = pd.read_csv(pilot / "data" / "pilot_w1.csv", dtype={"id": str, "remarks": str})
    options = {0.0: "Never", 1.0: "Sometimes; often", 2.0: "Often", -99.0: "Refused"}
    sav = tmp_path / "pilot.sav"
    pyreadstat.write_sav(
        frame.fillna({"remarks": ""}),
        sav,
        column_labels=["ID", "Date", "I feel  nervous.", "I feel calm.", "I worry.", "Total", "Age", "Anything else?"],
        variable_value_labels={f"anx{i}": options for i in (1, 2, 3)},
        missing_ranges={f"anx{i}": [-99] for i in (1, 2, 3)},
    )  # fmt: skip
    project = load_project(pilot)
    write_templates(project, "pilot_w1", sav)
    assert codebook_paths(project, "pilot_w1")[ITEMS].read_text(
        encoding="utf-8-sig"
    ).splitlines() == [
        "column,instrument,item,text,type,choices,reverse,min,max",
        "id,,,,,,,,",
        "date,,,,,,,,",
        'anx1,anx,anx1,I feel nervous.,choice,"0=Never; 1=Sometimes, often; 2=Often",,,',
        'anx2,anx,anx2,I feel calm.,choice,"0=Never; 1=Sometimes, often; 2=Often",,,',
        'anx3,anx,anx3,I worry.,choice,"0=Never; 1=Sometimes, often; 2=Often",,,',
        "anx_total,anx,anx_total,Total,number,,,,",
        "age,,age,Age,number,,,,",
        "remarks,,remarks,Anything else?,text,,,,",
    ]
    (tmp_path / "broken.sav").write_text("not spss", encoding="utf-8")
    with pytest.raises(CodebookError, match="not an SPSS data file"):
        spss.read_sav(tmp_path / "broken.sav")


def test_the_redcap_api_dictionary_reads_the_same(tmp_path):
    names = [
        "field_name",
        "form_name",
        "section_header",
        "field_type",
        "field_label",
        "select_choices_or_calculations",
        "field_note",
        "text_validation_type_or_show_slider_number",
        "text_validation_min",
        "text_validation_max",
        "identifier",
    ]
    web = redcap.read_dictionary(write_dictionary(tmp_path / "web.csv", REDCAP_HEADER))
    api = redcap.read_dictionary(write_dictionary(tmp_path / "api.csv", names))
    assert api == web
    assert set(web) == {
        "id",
        "mood_1",
        "mood_10",
        "race___1",
        "race___2",
        "smoker",
        "age",
        "pain",
        "remarks",
    }
    (tmp_path / "other.csv").write_text("column,label\nx,y\n", encoding="utf-8")
    with pytest.raises(CodebookError, match="not a REDCap data dictionary"):
        redcap.read_dictionary(tmp_path / "other.csv")


def run_cli(monkeypatch, capsys, *args: str) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["labcatalog", "codebook", *args])
    with pytest.raises(SystemExit) as caught:
        main()
    out = capsys.readouterr()
    return caught.value.code, out.out, out.err


def test_cli_creates_prompts_and_imports(pilot, tmp_path, monkeypatch, capsys):
    (pilot / "data" / "pilot_w1.csv").write_text(REDCAP_DATA, encoding="utf-8")
    dictionary = write_dictionary(tmp_path / "dictionary.csv", REDCAP_HEADER)
    p = ["-p", str(pilot)]
    code, _, err = run_cli(monkeypatch, capsys, "prompt", "pilot_w1", *p)
    assert (code, err.strip()) == (
        1,
        "Error: Create the codebook files first: labcatalog codebook create pilot_w1",
    )
    code, out, _ = run_cli(
        monkeypatch, capsys, "create", "pilot_w1", "--redcap", str(dictionary), *p
    )
    assert code == 0
    assert out.splitlines()[-1] == "Fill them in, then run: labcatalog codebook import pilot_w1"
    code, out, _ = run_cli(monkeypatch, capsys, "prompt", "pilot_w1", *p)
    assert code == 0 and "mood_1_w1,mood_scale,mood_1" in out
    code, out, _ = run_cli(monkeypatch, capsys, "import", "pilot_w1", *p)
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "No problems found."
    assert [line.endswith("pilot_w1.csv") for line in lines if line.startswith("Wrote ")] == [
        False,
        False,
        True,
    ]
    assert "Create studies/pilot.yaml with:" in lines
    code, _, err = run_cli(monkeypatch, capsys, "import", "pilot_w1", *p)
    assert (code, err.strip()) == (1, "Error: pilot_w1 already has a column map in maps/")
    code, _, err = run_cli(monkeypatch, capsys, "create", "nope", *p)
    assert (code, err.strip()) == (1, "Error: No dataset named nope in labcatalog.yaml")


def test_existing_instruments_are_reused_and_the_map_matches(mock_project):
    original = (mock_project / "maps" / "parent_w3.csv").read_text(encoding="utf-8")
    (mock_project / "maps" / "parent_w3.csv").unlink()
    study = mock_project / "studies" / "mock_study.yaml"
    study.write_text(
        study.read_text(encoding="utf-8").replace(", parent_w3]", "]"), encoding="utf-8"
    )
    project = load_project(mock_project)
    write_templates(project, "parent_w3")
    result = import_codebook(project, "parent_w3")
    assert result.issues == []
    assert (mock_project / "maps" / "parent_w3.csv").read_text(encoding="utf-8") == original
    assert result.reused == ["example_parent_stress", "example_child_sleep", "example_demographics"]
    [(instruction, lines)] = result.steps
    assert instruction == "In studies/mock_study.yaml, add parent_w3 to these administrations:"
    assert lines.splitlines() == [
        "  - {instrument: example_parent_stress, datasets: [parent_w1, parent_w2, parent_w3], target: self}",
        "  - {instrument: example_child_sleep, datasets: [parent_w1, parent_w2, parent_w3], target: child}",
        "  - {instrument: example_demographics, datasets: [parent_w1, parent_w2, parent_w3]}",
    ]


FEELINGS = """\
id: feelings
name: Feelings
response_sets:
  - id: often
    options:
      - {value: 0, label: Never}
      - {value: 1, label: Always}
default_response_set: often
items:
  - {id: feel_sad, text: "1. I feel SAD."}
"""


def test_a_dictionary_item_worded_like_a_catalog_item_reuses_it(pilot, tmp_path):
    (pilot / "data" / "pilot_w1.csv").write_text(REDCAP_DATA, encoding="utf-8")
    dictionary = write_dictionary(tmp_path / "dictionary.csv", REDCAP_HEADER)
    (pilot / "instruments" / "feelings.yaml").write_text(FEELINGS, encoding="utf-8")
    write_templates(load_project(pilot), "pilot_w1", dictionary)
    rows = codebook_paths(load_project(pilot), "pilot_w1")[ITEMS].read_text(encoding="utf-8-sig")
    lines = rows.splitlines()
    assert "mood_1_w1,feelings,feel_sad,,,,,," in lines
    assert any(line.startswith("mood_10_w1,mood_scale,mood_10,") for line in lines)


def test_wording_shared_by_two_catalog_items_is_not_guessed(pilot, tmp_path):
    (pilot / "data" / "pilot_w1.csv").write_text(REDCAP_DATA, encoding="utf-8")
    dictionary = write_dictionary(tmp_path / "dictionary.csv", REDCAP_HEADER)
    (pilot / "instruments" / "feelings.yaml").write_text(FEELINGS, encoding="utf-8")
    (pilot / "instruments" / "moods.yaml").write_text(
        FEELINGS.replace("feelings", "moods").replace("Feelings", "Moods"), encoding="utf-8"
    )
    write_templates(load_project(pilot), "pilot_w1", dictionary)
    rows = codebook_paths(load_project(pilot), "pilot_w1")[ITEMS].read_text(encoding="utf-8-sig")
    assert any(line.startswith("mood_1_w1,mood_scale,mood_1,") for line in rows.splitlines())


def test_a_qualtrics_style_label_matches_on_its_row_text(pilot, tmp_path):
    (pilot / "data" / "pilot_w1.csv").write_text(REDCAP_DATA, encoding="utf-8")
    dictionary = write_dictionary(tmp_path / "dictionary.csv", REDCAP_HEADER)
    text = dictionary.read_text(encoding="utf-8-sig")
    stem = "How often in the past week did you feel this way? - I feel sad"
    dictionary.write_text(text.replace("<p>I feel <i>sad</i></p>", stem), encoding="utf-8-sig")
    (pilot / "instruments" / "feelings.yaml").write_text(FEELINGS, encoding="utf-8")
    write_templates(load_project(pilot), "pilot_w1", dictionary)
    rows = codebook_paths(load_project(pilot), "pilot_w1")[ITEMS].read_text(encoding="utf-8-sig")
    assert "mood_1_w1,feelings,feel_sad,,,,,," in rows.splitlines()
