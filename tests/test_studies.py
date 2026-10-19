import difflib
from datetime import date

import pytest

from labcatalog.config import WaveConfig
from labcatalog.exceptions import EditError
from labcatalog.metadata import changes, records, studies
from labcatalog.metadata.validate import validate_project
from labcatalog.project import load_project


def edited(project, study="mock_study", **parts):
    found = project.config.studies[study]
    return studies.Edited(
        parts.get(
            "fields",
            {"label": found.label, "description": found.description, "reference": found.reference},
        ),
        parts.get("waves", studies.wave_rows(found)),
        parts.get("milestones", studies.milestone_rows(found)),
    )


def changed_lines(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line for line in diff if line[:1] in "+-" and line[:3] not in ("+++", "---")]


def test_unchanged_study_writes_the_file_back_as_it_was(mock_project):
    project = load_project(mock_project)
    change = studies.edit_change(project, "mock_study", edited(project))
    assert change.text == change.opened.text


def test_editing_dates_and_milestones_changes_only_those_lines(mock_project):
    project = load_project(mock_project)
    waves = studies.wave_rows(project.config.studies["mock_study"])
    waves[2]["end"] = "2026-10-31"
    waves.append({records.ORIGIN: None, "wave": "4", "start": "2027-03-01", "end": ""})
    milestones = studies.milestone_rows(project.config.studies["mock_study"])[1:]
    milestones.append({records.ORIGIN: None, "name": "Final report", "date": "2027-06-30"})
    change = studies.edit_change(
        project, "mock_study", edited(project, waves=waves, milestones=milestones)
    )
    assert changed_lines(change.opened.text, change.text) == [
        "-      3: {start: 2026-03-01}",
        "+      3: {start: 2026-03-01, end: 2026-10-31}",
        "+      4: {start: 2027-03-01}",
        "-      - {name: Interim report, date: 2026-12-15}",
        "+      - {name: Final report, date: 2027-06-30}",
    ]
    # The next section's comment stays after the study.
    assert "2027-06-30}\n\n# One entry per data file" in change.text
    assert changes.check(project, [change]) == []
    changes.write(project, [change])
    after = load_project(mock_project).config.studies["mock_study"]
    assert after.waves["4"] == WaveConfig(start=date(2027, 3, 1))
    assert [m.name for m in after.milestones] == ["Wave 3 data freeze", "Final report"]


def test_removing_every_milestone_keeps_the_comment_after_the_study(mock_project):
    project = load_project(mock_project)
    change = studies.edit_change(project, "mock_study", edited(project, milestones=[]))
    assert "milestones" not in change.text
    assert "{start: 2026-03-01}\n\n# One entry per data file" in change.text


def test_removing_a_wave_that_holds_datasets_is_caught(mock_project):
    project = load_project(mock_project)
    waves = studies.wave_rows(project.config.studies["mock_study"])[:2]
    change = studies.edit_change(project, "mock_study", edited(project, waves=waves))
    messages = [i.message for i in changes.check(project, [change])]
    assert any("wave 3 is not listed for study mock_study" in m for m in messages)


def test_bad_wave_rows_are_refused(mock_project):
    project = load_project(mock_project)
    waves = studies.wave_rows(project.config.studies["mock_study"])
    with pytest.raises(EditError, match="listed twice"):
        studies.edit_change(
            project, "mock_study", edited(project, waves=[*waves, dict(waves[0], _row=None)])
        )
    waves[0]["start"] = "March 2024"
    with pytest.raises(EditError, match="not a date"):
        studies.edit_change(project, "mock_study", edited(project, waves=waves))


def test_a_new_study_gets_its_entry_and_study_file(mock_project):
    project = load_project(mock_project)
    found = studies.new_study(project, "pilot", "Pilot Study")
    assert [c.path for c in found] == ["labcatalog.yaml", "studies/pilot.yaml"]
    assert "    label: Pilot Study\n\n# One entry per data file" in found[0].text
    assert changes.check(project, found) == []
    changes.write(project, found)
    after = load_project(mock_project)
    assert after.config.studies["pilot"].label == "Pilot Study"
    assert after.studies["pilot"].study == "pilot"
    with pytest.raises(EditError, match="already exists"):
        studies.new_study(after, "pilot", "")
    with pytest.raises(EditError, match="lower-case"):
        studies.new_study(after, "Pilot 2", "")


def test_methods_are_written_as_blocks(mock_project):
    project = load_project(mock_project)
    methods = dict(project.studies["mock_study"].methods)
    assert studies.text_change(project, "mock_study", methods) is None
    methods["eeg"] = "Recorded at 500 Hz.  \r\n\r\nCleaned by hand.\n\n"
    methods["saliva"] = ""
    change = studies.text_change(project, "mock_study", methods)
    assert "  eeg: |\n    Recorded at 500 Hz.\n\n    Cleaned by hand.\n  fmri: |" in change.text
    assert "  saliva:" not in change.text
    # Only the changed modalities differ from the file as it was.
    assert len(changed_lines(change.opened.text, change.text)) == 6
    assert changes.check(project, [change]) == []
    changes.write(project, [change])
    after = load_project(mock_project).studies["mock_study"]
    assert after.methods["eeg"] == "Recorded at 500 Hz.\n\nCleaned by hand.\n"


def test_a_dataset_can_have_its_own_methods(mock_project):
    path = mock_project / "studies" / "mock_study.yaml"
    own = "  child_w1: Children answered on paper.\n  eeg_w3: A 64-channel cap was used.\n"
    path.write_text(
        path.read_text(encoding="utf-8").replace("methods:\n", "methods:\n" + own), encoding="utf-8"
    )
    project = load_project(mock_project)
    written = project.studies["mock_study"].methods
    first = studies.wave_methods(project, "mock_study", "1")
    assert [(m, names) for m, names, _ in first[:2]] == [
        ("questionnaire", ["parent_w1", "parent_child_w1"]),
        ("questionnaire", ["child_w1"]),
    ]
    assert first[1][2] == written["child_w1"]
    assert ("eeg", [], written["eeg"]) in first
    assert ("eeg", [], written["eeg_w3"]) in studies.wave_methods(project, "mock_study", "3")


def test_a_methods_key_must_be_a_modality_or_a_dataset_of_the_study(mock_project):
    path = mock_project / "studies" / "mock_study.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "methods:\n", "methods:\n  meg: MEG.\n  eeg_w3: Own.\n"
    )
    path.write_text(text, encoding="utf-8")
    found = [i.message for i in validate_project(load_project(mock_project))]
    assert any(m.startswith("methods.meg:") for m in found)
    assert not any("child_w1" in m or "eeg_w3" in m for m in found)


def test_renaming_a_study_follows_it_into_every_file(mock_project):
    project = load_project(mock_project)
    found = studies.rename_study(project, "mock_study", "family_study")
    assert [(c.path, c.removed) for c in found] == [
        ("labcatalog.yaml", False),
        ("maps/roster_family_study.csv", False),
        ("maps/roster_mock_study.csv", True),
        ("studies/family_study.yaml", False),
        ("studies/mock_study.yaml", True),
    ]
    assert changes.check(project, found) == []
    changes.write(project, found)
    assert not (mock_project / "studies/mock_study.yaml").exists()
    after = load_project(mock_project)
    assert list(after.config.studies) == ["family_study"]
    assert {d.study for d in after.config.datasets} == {"family_study"}
    assert after.studies["family_study"].methods
    with pytest.raises(EditError, match="already exists"):
        studies.rename_study(after, "family_study", "family_study")


def test_deleting_a_new_study_leaves_the_file_as_it_was(mock_project):
    before = (mock_project / "labcatalog.yaml").read_text(encoding="utf-8")
    changes.write(
        load_project(mock_project), studies.new_study(load_project(mock_project), "pilot", "Pilot")
    )
    project = load_project(mock_project)
    found = studies.delete_study(project, "pilot")
    assert [(c.path, c.removed) for c in found] == [
        ("labcatalog.yaml", False),
        ("studies/pilot.yaml", True),
    ]
    assert found[0].text == before
    assert changes.check(project, found) == []


def test_deleting_a_study_takes_its_datasets_and_maps(mock_project):
    project = load_project(mock_project)
    found = studies.delete_study(project, "mock_study")
    removed = [c.path for c in found if c.removed]
    assert "maps/parent_w1.csv" in removed and removed[-1] == "studies/mock_study.yaml"
    # Each dataset's map, the roster's map and the study file.
    assert "maps/roster_mock_study.csv" in removed
    assert len(removed) == len(project.config.datasets) + 2
    assert "\nstudies: {}\n\n# One entry per data file" in found[0].text
    assert changes.check(project, found) == []
    changes.write(project, found)
    after = load_project(mock_project)
    assert after.config.studies == {} and after.config.datasets == []
    # The data stay where they were.
    assert (mock_project / "data/parent_w1.csv").exists()


def test_wave_status():
    today = date(2026, 10, 16)
    assert studies.wave_status(WaveConfig(), today) == ""
    assert studies.wave_status(WaveConfig(start=date(2027, 1, 1)), today) == "Planned"
    assert studies.wave_status(WaveConfig(start=date(2026, 3, 1)), today) == "Collecting"
    finished = WaveConfig(start=date(2025, 3, 1), end=date(2025, 10, 31))
    assert studies.wave_status(finished, today) == "Finished"
