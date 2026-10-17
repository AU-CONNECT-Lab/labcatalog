from labcatalog.metadata.browse import build_index, counts, facet_names, matches
from labcatalog.metadata.completeness import gaps
from labcatalog.pipeline import load_validated, run_validate

WAVE_1, WAVE_2, WAVE_3 = "mock_study/1", "mock_study/2", "mock_study/3"


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def index_for(root):
    project, issues = load_validated(root)
    assert project is not None, issues
    return build_index(project)


def test_facets_follow_the_config_and_list_only_values_present(mock_project):
    index = index_for(mock_project)
    assert [f.name for f in index.facets] == [
        "study",
        "wave",
        "coverage",
        "reporter",
        "target",
        "modality",
        "domain",
        "topics",
        "status",
    ]
    facets = {f.name: f for f in index.facets}
    assert facets["wave"].values == {WAVE_1: "1", WAVE_2: "2", WAVE_3: "3"}
    assert list(facets["domain"].values) == ["emotion", "family", "health", "media"]


def test_default_facets_add_choice_and_tags_fields(mock_project):
    edit(
        mock_project / "labcatalog.yaml",
        "facets: [study, wave, coverage, reporter, target, modality, domain, topics, status]",
        "{}",
    )
    project, _ = load_validated(mock_project)
    assert facet_names(project.config) == [
        "study",
        "wave",
        "coverage",
        "reporter",
        "target",
        "modality",
        "domain",
        "topics",
        "status",
    ]


def test_selections_must_hold_within_one_administration(mock_project):
    index = index_for(mock_project)
    assert list(matches(index, {"wave": {WAVE_1}})) == [
        "eeg_resting",
        "example_child_sleep",
        "example_demographics",
        "example_mood",
        "example_parent_stress",
        "eyetracking_faces",
        "fmri_resting",
        "saliva_cortisol",
    ]
    assert matches(index, {"wave": {WAVE_1}, "reporter": {"child"}}) == {
        "eeg_resting": ["eeg_w1"],
        "example_mood": ["child_w1"],
        "eyetracking_faces": ["eyetracking_w1"],
        "fmri_resting": ["fmri_w1"],
        "saliva_cortisol": ["saliva_w1"],
    }
    assert matches(index, {"domain": {"media", "emotion"}, "wave": set()}) == {
        "example_mood": ["child_w1", "child_w2", "child_w3"],
        "example_screen_time": ["child_w2", "child_w3"],
    }


def test_counts_keep_the_facets_own_values_open(mock_project):
    index = index_for(mock_project)
    found = counts(index, {"wave": {WAVE_1}})
    assert found["wave"] == {WAVE_1: 8, WAVE_2: 9, WAVE_3: 9}
    assert found["reporter"] == {"parent": 3, "child": 5}
    assert found["domain"] == {"emotion": 1, "family": 2, "health": 1, "media": 0}


def test_score_fields_describe_their_instrument(mock_project):
    index = index_for(mock_project)
    facets = {f.name: f for f in index.facets}
    assert list(facets["topics"].values) == [
        "negative affect",
        "positive affect",
        "parenting",
        "sleep",
    ]
    assert list(matches(index, {"topics": {"sleep"}})) == ["example_child_sleep", "example_mood"]


def test_search_names_and_optionally_item_text(mock_project):
    index = index_for(mock_project)
    assert list(matches(index, {}, "sleep")) == ["example_child_sleep", "example_mood"]
    assert matches(index, {}, "asleep") == {}
    assert list(matches(index, {}, "TIRED", items=True)) == [
        "example_child_sleep",
        "example_mood",
        "example_parent_stress",
    ]


def test_instruments_never_administered_still_appear_unfiltered(mock_project):
    (mock_project / "instruments" / "unused.yaml").write_text(
        "id: unused\nname: Not given yet\ncustom: {domain: media}\n", encoding="utf-8"
    )
    index = index_for(mock_project)
    assert matches(index, {})["unused"] == []
    assert "unused" in matches(index, {"domain": {"media"}})
    assert "unused" not in matches(index, {"wave": {WAVE_2}})


def test_browse_facets_are_validated(mock_project):
    edit(
        mock_project / "labcatalog.yaml",
        "facets: [study, wave, coverage, reporter, target, modality, domain, topics, status]",
        "facets: [study, wave, cohort, note, wave]",
    )
    edit(
        mock_project / "labcatalog.yaml",
        "custom_fields:\n",
        "custom_fields:\n  - {name: note, applies_to: instrument, type: text}\n"
        "  - {name: wave, applies_to: dataset, type: choice, choices: [a]}\n",
    )
    messages = {i.code: i.message for i in run_validate(mock_project)}
    assert "'cohort' is neither a built-in facet" in messages["unknown_reference"]
    assert "'wave' is listed twice" in messages["duplicate_id"]
    found = [i.message for i in run_validate(mock_project) if i.code == "invalid_value"]
    assert any("'note' is a text field" in m for m in found)
    assert any("custom_fields (wave): the name is taken" in m for m in found)


def test_coverage_counts_the_waves_with_data(mock_project):
    index = index_for(mock_project)
    facets = {f.name: f for f in index.facets}
    assert list(facets["coverage"].values) == ["every wave", "2 waves", "1 wave"]
    assert "example_mood" in matches(index, {"coverage": {"every wave"}})
    assert "example_screen_time" not in matches(index, {"coverage": {"every wave"}})


def test_status_lists_what_the_catalog_lacks(mock_project):
    (mock_project / "instruments" / "unused.yaml").write_text(
        "id: unused\nname: Not given yet\n", encoding="utf-8"
    )
    project, _ = load_validated(mock_project)
    index = build_index(project)
    facets = {f.name: f for f in index.facets}
    values = list(facets["status"].values)
    assert values[0] == "complete" and values[-1] == "not in a dataset" and "no items" in values
    assert list(matches(index, {"status": {"not in a dataset"}})) == ["unused"]
    complete = matches(index, {"status": {"complete"}})
    assert complete and all(not gaps(project.instruments[i]) for i in complete)


def test_modality_values_read_as_their_labels(mock_project):
    index = index_for(mock_project)
    facets = {f.name: f for f in index.facets}
    assert facets["modality"].values["fmri"] == "fMRI"
