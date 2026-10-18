from labcatalog.gui import edit_form
from labcatalog.metadata import editing, forms

MOOD = "instruments/example_mood.yaml"


def opened(root, relative):
    return editing.open_file(root, relative).text


def test_an_instrument_form_offers_the_files_own_ids(mock_project):
    found = {s.key: s for s in forms.sections(mock_project, MOOD, opened(mock_project, MOOD))}
    assert list(found)[:5] == ["about", "response_sets", "items", "scores", "references"]
    assert "ems_1" in found["scores"].options["items"]
    assert found["items"].options["response_set"]
    assert "questionnaire" in found["about"].options["kind"]


def test_settings_and_study_forms_offer_the_projects_lists(mock_project):
    config = forms.sections(
        mock_project, "labcatalog.yaml", opened(mock_project, "labcatalog.yaml")
    )
    assert "parent" in config[0].options["reporter"]
    study = next((mock_project / "studies").glob("*.yaml")).relative_to(mock_project).as_posix()
    administrations = forms.sections(mock_project, study, opened(mock_project, study))[0]
    assert "example_mood" in administrations.options["instrument"]
    assert "child_w1" in administrations.options["datasets"]


def test_an_untouched_form_writes_the_file_back_as_it_was(mock_project):
    for relative in (MOOD, "labcatalog.yaml"):
        text = opened(mock_project, relative)
        assert edit_form.open_form(mock_project, relative, text).text(text) == text


def test_form_changes_reach_the_file_and_pass_the_checks(mock_project):
    text = opened(mock_project, MOOD)
    form = edit_form.open_form(mock_project, MOOD, text)
    form.rows["about"][0]["name"] = "Renamed Mood Scale"
    items = form.rows["items"]
    taken = [row["id"] for row in items]
    items.append({**items[-1], "_row": None, "id": forms.next_id(taken, "item"), "text": "New"})
    written = form.text(text)
    assert "name: Renamed Mood Scale" in written
    assert "ems_10" in written and written.count("ems_1,") == text.count("ems_1,")
    assert editing.check_text(MOOD, written) == []


def test_renaming_a_response_set_renames_what_names_it(mock_project):
    text = opened(mock_project, MOOD)
    form = edit_form.open_form(mock_project, MOOD, text)
    form.rows["items"][0]["response_set"] = "frequency"
    form.sections = forms.rename_set(form.sections, form.rows, "frequency", "how_often")
    assert {row["id"] for row in form.rows["response_sets"]} == {"how_often"}
    assert form.rows["about"][0]["default_response_set"] == "how_often"
    assert form.rows["items"][0]["response_set"] == "how_often"
    items = next(s for s in form.sections if s.key == "items")
    assert items.options["response_set"] == ("how_often",)
    written = form.text(text)
    assert "frequency" not in written
    assert editing.check_text(MOOD, written) == []


def test_new_ids_continue_a_numbered_run():
    assert forms.next_id(["ems_1", "ems_2"], "item") == "ems_3"
    assert forms.next_id(["total"], "score") == "score_1"
    assert forms.next_id(["set_1", "agree"], "set") == "set_2"
    assert forms.next_id([], "item") == "item_1"
