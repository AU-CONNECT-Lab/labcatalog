from labcatalog.metadata.browse import (
    HAS_ERRORS,
    HAS_WARNINGS,
    NO_PROBLEMS,
    PROBLEMS,
    build_dataset_index,
    build_index,
    counts,
    dataset_counts,
    dataset_matches,
    facet_names,
    matches,
)
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
        "example_worries_temper",
        "eyetracking_faces",
        "fmri_resting",
        "saliva_cortisol",
    ]
    assert matches(index, {"wave": {WAVE_1}, "reporter": {"child"}}) == {
        "eeg_resting": ["eeg_w1"],
        "example_mood": ["child_w1"],
        "example_worries_temper": ["child_w1"],
        "eyetracking_faces": ["eyetracking_w1"],
        "fmri_resting": ["fmri_w1"],
        "saliva_cortisol": ["saliva_w1"],
    }
    assert matches(index, {"domain": {"media", "emotion"}, "wave": set()}) == {
        "example_mood": ["child_w1", "child_w2", "child_w3"],
        "example_screen_time": ["child_w2", "child_w3"],
        "example_worries_temper": [
            "parent_child_w1",
            "parent_child_w2",
            "parent_child_w3",
            "child_w1",
            "child_w2",
            "child_w3",
        ],
    }


def test_counts_keep_the_facets_own_values_open(mock_project):
    index = index_for(mock_project)
    found = counts(index, {"wave": {WAVE_1}})
    assert found["wave"] == {WAVE_1: 9, WAVE_2: 10, WAVE_3: 10}
    assert found["reporter"] == {"parent": 4, "child": 6}
    assert found["domain"] == {"emotion": 2, "family": 2, "health": 1, "media": 0}


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


def test_search_finds_an_instrument_by_its_data_column(mock_project):
    index = index_for(mock_project)
    assert list(matches(index, {}, "ecs_3_w2")) == ["example_child_sleep"]
    assert list(matches(index, {}, "ECS_3")) == ["example_child_sleep"]


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


def add_part_fields(root):
    # An item field on one mood item and a study field on the mock study.
    edit(
        root / "labcatalog.yaml",
        "custom_fields:\n",
        "custom_fields:\n"
        "  - {name: format, applies_to: item, type: choice, choices: [statement, question]}\n"
        "  - {name: funder, applies_to: study, type: choice, choices: [nih, nsf]}\n",
    )
    edit(
        root / "labcatalog.yaml",
        "    reference: mockstudy2026\n",
        "    reference: mockstudy2026\n    custom: {funder: nih}\n",
    )
    edit(
        root / "instruments" / "example_mood.yaml",
        "{id: ems_1, text: I felt happy., reverse: true}",
        "{id: ems_1, text: I felt happy., reverse: true, custom: {format: statement}}",
    )
    edit(
        root / "labcatalog.yaml",
        "facets: [study, wave, coverage, reporter, target, modality, domain, topics, status]",
        "facets: [study, wave, coverage, reporter, target, modality, domain, topics, format, "
        "funder, status]",
    )


def test_item_and_study_fields_find_their_instruments(mock_project):
    add_part_fields(mock_project)
    index = index_for(mock_project)
    assert list(matches(index, {"format": {"statement"}})) == ["example_mood"]
    given = {row.instrument_id for row in index.rows if row.dataset is not None}
    assert set(matches(index, {"funder": {"nih"}})) == given
    assert "statement" in index.text["example_mood"]


def test_item_and_study_fields_are_held_to_their_declaration(mock_project):
    add_part_fields(mock_project)
    edit(mock_project / "labcatalog.yaml", "custom: {funder: nih}", "custom: {funder: nasa}")
    edit(
        mock_project / "instruments" / "example_mood.yaml",
        "{format: statement}",
        "{domain: emotion}",
    )
    messages = [i.message for i in run_validate(mock_project)]
    assert any(m.startswith("studies.mock_study.custom.funder:") for m in messages)
    assert "items[1] (ems_1).custom.domain: declared for instrument, not item" in messages


def add_rdoc(root):
    edit(
        root / "labcatalog.yaml",
        "custom_fields:\n",
        "custom_fields:\n"
        "  - {name: rdoc, label: RDoC, applies_to: score, type: tags, vocabulary: rdoc}\n",
    )
    edit(
        root / "labcatalog.yaml",
        "facets: [study, wave, coverage, reporter, target, modality, domain, topics, status]",
        "facets: [study, rdoc, status]",
    )
    edit(
        root / "instruments" / "example_mood.yaml",
        "custom: {topics: [negative affect]}}\n  - {id: ems_sadness",
        "custom: {topics: [negative affect], rdoc: [Loss]}}\n  - {id: ems_sadness",
    )
    edit(
        root / "instruments" / "example_child_sleep.yaml",
        "custom: {topics: [sleep]}}",
        "custom: {topics: [sleep], rdoc: [Sleep-Wakefulness, Social Processes]}}",
    )


def test_a_vocabulary_gives_the_choices_and_a_group_finds_its_terms(mock_project):
    add_rdoc(mock_project)
    index = index_for(mock_project)
    rdoc = next(f for f in index.facets if f.name == "rdoc")
    assert list(rdoc.values) == [
        "Negative Valence Systems",
        "Loss",
        "Social Processes",
        "Arousal and Regulatory Systems",
        "Sleep-Wakefulness",
    ]
    assert rdoc.parents == {
        "Loss": "Negative Valence Systems",
        "Sleep-Wakefulness": "Arousal and Regulatory Systems",
    }
    assert list(matches(index, {"rdoc": {"Negative Valence Systems"}})) == ["example_mood"]
    assert list(matches(index, {"rdoc": {"Social Processes"}})) == ["example_child_sleep"]
    found = counts(index, {})["rdoc"]
    assert found["Arousal and Regulatory Systems"] == found["Sleep-Wakefulness"] == 1


def test_a_vocabulary_holds_its_tags_and_stands_alone(mock_project):
    add_rdoc(mock_project)
    edit(mock_project / "instruments" / "example_mood.yaml", "rdoc: [Loss]", "rdoc: [Grief]")
    messages = [i.message for i in run_validate(mock_project)]
    assert any("custom.rdoc" in m and "Grief" in m for m in messages)
    edit(mock_project / "labcatalog.yaml", "vocabulary: rdoc}", "vocabulary: rdoc, choices: [a]}")
    assert any("not both" in m for m in (i.message for i in run_validate(mock_project)))
    edit(mock_project / "labcatalog.yaml", "vocabulary: rdoc, choices: [a]}", "vocabulary: dsm}")
    assert any("no vocabulary dsm" in m for m in (i.message for i in run_validate(mock_project)))


def dataset_index_for(root, levels=None):
    project, issues = load_validated(root)
    assert project is not None, issues
    return build_dataset_index(project, levels or {})


def test_datasets_filter_by_study_wave_and_modality(example_project):
    index = dataset_index_for(example_project)
    facets = {f.name: f for f in index.facets}
    assert list(facets) == ["study", "wave", "reporter", "modality", PROBLEMS]
    assert facets["wave"].values["mock_study_2/baseline"].endswith(": baseline")
    found = dataset_matches(index, {"study": {"mock_study"}, "modality": {"eeg"}})
    assert found == ["eeg_w1", "eeg_w3"]
    found = dataset_matches(index, {"wave": {"mock_study_2/baseline"}, "reporter": {"child"}})
    assert found == ["s2_child_baseline", "s2_watch_baseline"]


def test_dataset_search_reaches_instruments_and_columns(example_project):
    index = dataset_index_for(example_project)
    by_column = dataset_matches(index, {}, "eps_1_w1")
    assert by_column == ["parent_w1"]
    by_instrument = set(dataset_matches(index, {}, "example_parent_stress"))
    assert "parent_w1" in by_instrument and "child_w1" not in by_instrument
    assert dataset_matches(index, {}, "eps_1_w1 eeg") == []


def test_dataset_counts_keep_the_facets_own_values_open(example_project):
    index = dataset_index_for(example_project)
    found = dataset_counts(index, {"study": {"mock_study_2"}, "modality": {"actigraphy"}})
    assert found["study"]["mock_study"] == 0
    assert found["modality"]["questionnaire"] == 4
    assert found["modality"]["actigraphy"] == 2


def test_datasets_filter_by_their_worst_problem(example_project):
    levels = {"parent_w1": {"warning", "error"}, "child_w1": {"warning"}}
    index = dataset_index_for(example_project, levels)
    assert dataset_matches(index, {PROBLEMS: {HAS_ERRORS}}) == ["parent_w1"]
    assert dataset_matches(index, {PROBLEMS: {HAS_WARNINGS}}) == ["child_w1"]
    assert len(dataset_matches(index, {PROBLEMS: {NO_PROBLEMS}})) == len(index.datasets) - 2


def test_dataset_search_reaches_every_setting(example_project):
    index = dataset_index_for(example_project)
    config = load_validated(example_project)[0].config
    first = config.datasets[0]
    assert dataset_matches(index, {}, first.path) == [first.name]
    assert dataset_matches(index, {}, str(first.snapshot_date))
