import yaml

from labcatalog.gui import methods
from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project
from labcatalog.reports import participants


def test_default_paragraph_gives_waves_counts_and_retention(mock_project):
    result = run_catalog(mock_project)
    text = participants.paragraph(result.project, result.summary, "mock_study")
    assert text.startswith(
        "Data were collected in three waves: Wave 1 (2024-03-01 to 2024-10-31), Wave 2"
    )
    assert "Wave 3 (since 2026-03-01)." in text
    # The parents' checklists on each child count by the parent who filled them in.
    assert "At Wave 1, 192 parent and 217 child respondents from 191 family groups" in text
    assert "At Wave 2, 155 of 192 parent respondents (81%) and 169 of 217 child" in text
    assert "12 parent and 19 child respondents were new. Data from EEG" in text
    assert "Data from questionnaires" not in text
    # Gender and age are left blank for the author to fill in.
    assert "took part. Of the parent respondents, [ ]% were" in text
    assert text.count("mean age was [ ] years (SD = [ ])") == 2
    assert text.endswith(
        "Data from salivary cortisol were available for 131 of 217 child respondents at Wave 1 "
        "(60%) and 101 of 174 at Wave 3 (58%). Of these, 69 of the 131 from Wave 1 had them "
        "again at Wave 3 (53%)."
    )
    ids = {
        d.config.wave: set(d.frame[d.id_column])
        for d in result.datasets.values()
        if d.config.modality == "saliva"
    }
    assert len(ids["1"] & ids["3"]) == 69
    # EEG skipped Wave 2, so its returning count is against Wave 1.
    assert "90 of the 141 from Wave 1 had them again at Wave 3" in text


def test_modality_table_counts_each_modality_against_its_wave(mock_project):
    result = run_catalog(mock_project)
    columns, rows = methods.modality_table(result, "mock_study")
    assert [c["label"] for c in columns] == [
        "Modality",
        "Reporter",
        "Wave 1",
        "Wave 2",
        "Wave 2 returning",
        "Wave 3",
        "Wave 3 returning",
    ]
    eeg = next(r for r in rows if r["modality"] == "EEG")
    assert (eeg["w0"], eeg["w2"]) == ("141 (65%)", "125 (72%)") and "w1" not in eeg
    # EEG skipped wave 2, so its returning count is against wave 1.
    ids = {
        d.config.wave: set(d.frame[d.id_column])
        for d in result.datasets.values()
        if d.config.modality == "eeg"
    }
    both = len(ids["1"] & ids["3"])
    assert eeg["back2"] == f"{both} ({round(100 * both / 141)}%)" and "back1" not in eeg
    assert rows[0] == {
        "modality": "questionnaires",
        "reporter": "parent",
        "w0": "192 (100%)",
        "w1": "170 (100%)",
        "back1": "155 (81%)",
        "w2": "160 (100%)",
        "back2": next(
            f"{r.n_from_previous} ({round(100 * r.n_from_previous / 170)}%)"
            for r in result.summary.retention
            if (r.reporter, r.wave) == ("parent", "3")
        ),
    }


def test_a_modality_label_must_name_a_modality(mock_project):
    config = mock_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["vocab"]["modality_labels"]["meg"] = "MEG"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    issues = validate_project(load_project(mock_project))
    assert [i.message for i in issues if i.code == "not_in_vocab"] == [
        "vocab.modality_labels.meg: 'meg' is not in vocab.modalities"
    ]


def test_study_template_wins_over_the_project_one(mock_project):
    config = mock_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["templates"] = {"participants": "{study}: {n_waves} waves. {retention}"}
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = run_catalog(mock_project)
    text = participants.paragraph(result.project, result.summary, "mock_study")
    assert text.startswith("Mock Family Study: three waves. At Wave 2,")
    content = next(iter(result.project.studies.values()))
    content.participants = "{counts}"
    assert participants.wording_for(result.project, "mock_study").text("participants") == "{counts}"


def test_unknown_participants_placeholder_is_an_error(mock_project):
    config = mock_project / "labcatalog.yaml"
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["templates"] = {"participants": "{name} took part."}
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    issues = validate_project(load_project(mock_project))
    found = [i for i in issues if i.message.startswith("participants:")]
    assert len(found) == 1 and "unknown placeholder {name}" in found[0].message


def test_retention_table_shows_who_came_back(mock_project):
    result = run_catalog(mock_project)
    columns, rows = methods.retention_table(result, "mock_study")
    labels = [c["label"] for c in columns]
    assert labels[:4] == ["Wave", "Dates", "Parent n", "Parent returning"]
    assert labels[-2:] == ["Family groups", "With every reporter"]
    assert (rows[0]["n_parent"], rows[0]["back_parent"]) == (192, "")
    assert rows[1]["back_parent"] == "155 (81%)"


def test_one_reporter_is_not_named_in_the_paragraph(mock_project):
    result = run_catalog(mock_project)
    summary = result.summary
    children = summary.model_copy(
        update={
            "retention": [r for r in summary.retention if r.reporter == "child"],
            "modalities": [m for m in summary.modalities if m.reporter == "child"],
            "groups": [],
        }
    )
    text = participants.paragraph(result.project, children, "mock_study")
    assert "At Wave 1, 217 respondents took part." in text
    assert "At Wave 2, 169 of 217 respondents (78%) from Wave 1 took part again" in text
    assert "19 respondents were new" in text
    assert "131 of 217 respondents at Wave 1" in text and "child" not in text
