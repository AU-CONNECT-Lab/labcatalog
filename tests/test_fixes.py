from labcatalog.metadata import changes, fixes
from labcatalog.pipeline import run_catalog, run_check, run_validate
from labcatalog.project import load_project


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply(root, found):
    found = found if isinstance(found, list) else [found]
    project = load_project(root)
    assert changes.check(project, found) == []
    changes.write(project, found)


def codes(issues):
    return {i.code for i in issues}


def test_an_unlisted_column_is_added_to_the_map(mock_project):
    [issue] = [i for i in run_check(mock_project).issues if i.code == "column_unmapped"]
    assert issue.details == {"dataset": "child_w3", "columns": ["notes"]}
    project = load_project(mock_project)
    apply(mock_project, fixes.map_rows(project, "child_w3", [("notes", "", "")]))
    assert "column_unmapped" not in codes(run_check(mock_project).issues)


def test_a_misspelled_word_is_replaced_or_added(mock_project):
    config = mock_project / "labcatalog.yaml"
    edit(config, "wave: 1, reporter: child", "wave: 1, reporter: chlid")
    edit(config, "wave: 3, reporter: child", "wave: 3, reporter: chlid")
    found = [i for i in run_validate(mock_project) if i.code == "not_in_vocab"]
    issue = found[0]
    details = issue.details
    assert (details["vocab"], details["value"], details["field"]) == (
        "reporters",
        "chlid",
        "reporter",
    )
    project = load_project(mock_project)
    assert fixes.closest("chlid", project.config.vocab.reporters) == "child"
    before = config.read_text(encoding="utf-8")
    apply(mock_project, fixes.replace_word(project, [details], "child"))
    assert len([i for i in run_validate(mock_project) if i.code == "not_in_vocab"]) == 1
    config.write_text(before, encoding="utf-8")
    places = [i.details for i in found]
    apply(mock_project, fixes.replace_word(load_project(mock_project), places, "child"))
    assert "not_in_vocab" not in codes(run_validate(mock_project))
    config.write_text(before, encoding="utf-8")
    apply(mock_project, fixes.add_to_vocab(load_project(mock_project), "reporters", "chlid"))
    assert "not_in_vocab" not in codes(run_validate(mock_project))
    assert "reporters: [parent, child, chlid]" in config.read_text(encoding="utf-8")


def test_a_misspelled_target_is_fixed_in_the_study_file(mock_project):
    study = mock_project / "studies" / "mock_study.yaml"
    edit(
        study,
        "datasets: [child_w1, child_w2, child_w3], target: self",
        "datasets: [child_w1, child_w2, child_w3], target: slef",
    )
    [issue] = [i for i in run_validate(mock_project) if i.code == "not_in_vocab"]
    assert issue.details["study"] == "mock_study" and issue.details["administration"] == 2
    apply(mock_project, fixes.replace_word(load_project(mock_project), [issue.details], "self"))
    assert run_validate(mock_project) == []


def test_an_unmapped_item_is_mapped_or_recorded_as_not_asked(mock_project):
    map_file = mock_project / "maps" / "child_w1.csv"
    edit(map_file, "ems_9_w1,example_mood,ems_9\n", "")
    before = map_file.read_text(encoding="utf-8")
    [issue] = [i for i in run_validate(mock_project) if i.code == "unmapped_item"]
    assert issue.details == {
        "dataset": "child_w1",
        "instrument": "example_mood",
        "items": ["ems_9"],
    }
    project = load_project(mock_project)
    assert fixes.free_columns(project, "child_w1", ["pid", "ems_9_w1"]) == ["ems_9_w1"]
    apply(
        mock_project, fixes.map_rows(project, "child_w1", [("ems_9_w1", "example_mood", "ems_9")])
    )
    assert run_validate(mock_project) == []
    map_file.write_text(before, encoding="utf-8")
    apply(
        mock_project,
        fixes.not_asked(load_project(mock_project), "child_w1", "example_mood", ["ems_9"]),
    )
    assert run_validate(mock_project) == []
    text = (mock_project / "studies" / "mock_study.yaml").read_text(encoding="utf-8")
    assert "{item: ems_9, dataset: child_w1, dropped: true}" in text


def find(root, code, text):
    return next(i for i in run_check(root).issues if i.code == code and text in i.message)


def test_a_data_problem_shows_its_rows(mock_project):
    result = run_catalog(mock_project)
    spaced = next(i for i in result.report.issues if i.code == "id_whitespace")
    [row] = fixes.evidence(result.datasets[spaced.details["dataset"]], spaced)
    assert row["id"] == "' 1031P'"
    stray = next(i for i in result.report.issues if i.message.startswith("eps_4_w1"))
    [row] = fixes.evidence(result.datasets["parent_w1"], stray)
    assert row["value"] == "7" and stray.details["values"] == ["7"]


def test_a_stray_value_becomes_an_option_or_a_missing_code(mock_project):
    stray = find(mock_project, "unexpected_value", "eps_4_w1")
    project = load_project(mock_project)
    variables = run_catalog(mock_project).catalog.variables
    set_id = next(v.response_set for v in variables if v.column == "eps_4_w1")
    apply(
        mock_project,
        fixes.add_options(project, stray.details["instrument"], set_id, [("7", "Always")]),
    )
    assert not any(i.message.startswith("eps_4_w1") for i in run_check(mock_project).issues)

    find(mock_project, "unexpected_value", "ems_3_w1")
    apply(
        mock_project,
        fixes.add_missing_codes(load_project(mock_project), "child_w1", [("4", "skipped")], False),
    )
    assert not any(i.message.startswith("ems_3_w1") for i in run_check(mock_project).issues)
    config = load_project(mock_project).config
    own = next(d for d in config.datasets if d.name == "child_w1").missing_codes
    assert [m.code for m in own] == [-99, -98, -97, "", 4]

    find(mock_project, "unexpected_value", "dem_age_w2")
    apply(
        mock_project,
        fixes.add_missing_codes(load_project(mock_project), "parent_w2", [("45", "typo")], True),
    )
    assert not any(i.message.startswith("dem_age_w2") for i in run_check(mock_project).issues)


def test_a_mistyped_id_is_swapped_for_the_one_meant(mock_project):
    study = mock_project / "studies" / "mock_study.yaml"
    old = "{instrument: example_mood, datasets: [child_w1, child_w2,"
    edit(study, old, "{instrument: example_mod, datasets: [child_w1, chld_w2,")
    edit(
        mock_project / "instruments" / "example_parent_stress.yaml", "id: agreement", "id: agrement"
    )
    seen = set()
    # One at a time, as a person would: a wrong instrument hides the check of its datasets.
    while found := [
        i
        for i in run_validate(mock_project)
        if i.code == "unknown_reference" and "path" in i.details
    ]:
        issue = found[0]
        seen.add(issue.details["value"])
        wanted = fixes.closest(issue.details["value"], issue.details["choices"])
        path = issue.location.split(":")[0]
        project = load_project(mock_project)
        change = fixes.replace_at(project, path, issue.details["path"], wanted)
        # Only the typo the wrong instrument hid may come up; the panel then offers Save anyway.
        revealed = [i.details.get("value") for i in changes.check(project, [change])]
        assert set(revealed) <= {"chld_w2"}
        changes.write(project, [change])
    assert {"example_mod", "chld_w2", "agreement"} <= seen
    assert run_validate(mock_project) == []


def test_a_renamed_column_is_put_back_or_its_row_taken_out(mock_project):
    map_file = mock_project / "maps" / "child_w1.csv"
    edit(map_file, "pid,,\n", "pid,,\n\n")
    edit(map_file, "ems_2_w1,example_mood,ems_2", "ems_2_wl,example_mood,ems_2")
    [issue] = [i for i in run_check(mock_project).issues if i.code == "column_missing"]
    line = map_file.read_text(encoding="utf-8").split("\n").index("ems_2_wl,example_mood,ems_2")
    assert issue.details == {"dataset": "child_w1", "column": "ems_2_wl", "line": line + 1}
    assert issue.location == f"maps/child_w1.csv:{line + 1}"
    project = load_project(mock_project)
    free = fixes.free_columns(project, "child_w1", ["pid", "ems_2_w1", "visit_date"])
    assert fixes.closest("ems_2_wl", free) == "ems_2_w1"
    before = map_file.read_text(encoding="utf-8")
    apply(mock_project, fixes.map_line(project, "child_w1", issue.details["line"], "ems_2_w1"))
    assert map_file.read_text(encoding="utf-8") == before.replace("ems_2_wl", "ems_2_w1")
    found = codes(run_check(mock_project).issues)
    assert "column_missing" not in found and "column_unmapped" not in found
    map_file.write_text(before, encoding="utf-8")
    taken = fixes.map_line(load_project(mock_project), "child_w1", issue.details["line"], None)
    assert "ems_2_wl" not in taken.text and taken.text.count("\n") == before.count("\n") - 1


def test_a_row_listed_twice_in_the_map_is_taken_out(mock_project):
    map_file = mock_project / "maps" / "child_w1.csv"
    before = map_file.read_text(encoding="utf-8")
    map_file.write_text(before + "ems_1_w1,example_mood,ems_1\n", encoding="utf-8")
    last = before.count("\n") + 1
    [issue] = [i for i in run_validate(mock_project) if i.code == "duplicate_id"]
    assert issue.details == {"dataset": "child_w1", "lines": [4, last]}
    project = load_project(mock_project)
    assert fixes.map_lines(project, "child_w1")[3] == "ems_1_w1,example_mood,ems_1"
    apply(mock_project, fixes.map_line(project, "child_w1", last, None))
    assert map_file.read_text(encoding="utf-8") == before
    map_file.write_text(before + "ems_1_again,example_mood,ems_1\n", encoding="utf-8")
    [issue] = [i for i in run_validate(mock_project) if i.code == "duplicate_id"]
    assert "already mapped to ems_1_w1" in issue.message
    assert issue.details["lines"] == [4, last]


def test_a_missing_code_that_is_an_answer_is_taken_out(mock_project):
    edit(
        mock_project / "instruments" / "example_mood.yaml",
        "{value: 0, label: Never}",
        "{value: -99, label: Never}",
    )
    found = [i for i in run_validate(mock_project) if i.code == "missing_code_collision"]
    assert len(found) > 1 and all(i.details["value"] == "-99" for i in found)
    first, second = found[0].details["dataset"], found[1].details["dataset"]
    apply(mock_project, fixes.drop_missing_code(load_project(mock_project), first, "-99", False))
    project = load_project(mock_project)
    own = next(d for d in project.config.datasets if d.name == first).missing_codes
    assert [str(m.code) for m in own] == ["-98", "-97", ""]
    left = {
        i.details["dataset"]
        for i in run_validate(mock_project)
        if i.code == "missing_code_collision"
    }
    assert first not in left and second in left
    apply(mock_project, fixes.drop_missing_code(project, second, "-99", True))
    assert "missing_code_collision" not in codes(run_validate(mock_project))


def test_a_mistyped_reference_key_is_swapped_for_one_in_the_bib(mock_project):
    edit(mock_project / "instruments" / "example_mood.yaml", "key: example2019", "key: exampel2019")
    [issue] = [i for i in run_validate(mock_project) if i.code == "reference_missing"]
    details = issue.details
    assert details["path"] == ["references", 0, "key"] and details["value"] == "exampel2019"
    assert fixes.closest("exampel2019", details["choices"]) == "example2019"
    project = load_project(mock_project)
    apply(
        mock_project,
        fixes.replace_at(project, issue.location, details["path"], "example2019"),
    )
    assert "reference_missing" not in codes(run_validate(mock_project))
