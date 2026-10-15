from pathlib import Path

from labcatalog.browse import build_index, matches
from labcatalog.gui import datasets, instruments, overview
from labcatalog.gui.common import location_path
from labcatalog.pipeline import run_catalog


def test_location_path_drops_the_line_number():
    root = Path("project")
    assert location_path(root, "studies/demo_study.yaml:5") == root / "studies/demo_study.yaml"
    outside = Path.cwd() / "data" / "parent_w1.csv"
    assert location_path(root, f"{outside.as_posix()}:3") == outside


def test_wave_table(mock_project):
    result = run_catalog(mock_project)
    _, waves = overview.wave_table(result)
    assert [(w["wave"], w["n_parent"], w["n_child"]) for w in waves] == [
        ("1", 146, 140),
        ("2", 128, 116),
        ("3", 60, 56),
    ]


def test_instrument_list_shows_only_the_matched_datasets(mock_project):
    result = run_catalog(mock_project)
    index = build_index(result.project)
    found = matches(index, {"reporter": {"child"}})
    columns, rows = instruments.list_table(result, found)
    assert [c["label"] for c in columns[-3:]] == ["child_w1", "child_w2", "child_w3"]
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"example_mood", "example_screen_time"}
    screen = by_id["example_screen_time"]
    assert (screen["d0"], screen["d1"], screen["d2"]) == ("", 116, 56)
    assert by_id["example_mood"]["reporters"] == "child"


def test_instrument_items_list_each_dataset_column(mock_project):
    result = run_catalog(mock_project)
    columns, rows = instruments.item_table(result, result.project.instruments["example_mood"])
    assert [c["label"] for c in columns[-3:]] == ["child_w1", "child_w2", "child_w3"]
    assert (rows[0]["d0"], rows[0]["d2"]) == ("ems_1_w1", "ems_1_w3")


def test_dataset_issues_cover_its_data_file_only(mock_project):
    result = run_catalog(mock_project)
    codes = [i.code for i in datasets.dataset_issues(result, "child_w1")]
    assert sorted(codes) == ["same_answer", "unexpected_value"]


def test_dataset_page_lists_each_file_with_the_study_citation(mock_project):
    config = mock_project / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace(
            "    label: Mock Family Study\n",
            "    label: Mock Family Study\n"
            "    citation: Example, A. (2026). Mock Family Study.\n"
            "    doi: 10.0000/mock\n",
        ),
        encoding="utf-8",
    )
    result = run_catalog(mock_project)
    study = result.project.config.studies["mock_study"]
    assert (study.citation, study.doi) == ("Example, A. (2026). Mock Family Study.", "10.0000/mock")
    _, rows = datasets.dataset_table(result, result.summary.datasets[:3])
    assert [(r["name"], r["wave"], r["reporter"]) for r in rows] == [
        ("parent_w1", "1", "parent"),
        ("parent_w2", "2", "parent"),
        ("parent_w3", "3", "parent"),
    ]
    _, instruments = datasets.completeness_table(result, result.summary.datasets[0])
    assert {r["id"] for r in instruments} == {
        "example_parent_stress",
        "example_child_sleep",
        "example_demographics",
    }


def test_item_total_and_stability_tables_have_a_column_per_wave(mock_project):
    result = run_catalog(mock_project)
    mood = result.project.instruments["example_mood"]
    columns, rows = instruments.item_total_waves(result, mood)
    assert [c["label"] for c in columns[2:]] == [
        "Wave 1 (α 0.86)",
        "Wave 2 (α 0.88)",
        "Wave 3 (α 0.85)",
    ]
    assert [r["item"] for r in rows] == [f"ems_{i}" for i in range(1, 7)]
    assert all(r["d0"] and r["d2"] for r in rows)
    columns, rows = instruments.stability_table(result, mood)
    assert [c["label"] for c in columns[1:]] == ["Wave 1 → Wave 2", "Wave 2 → Wave 3"]
    total = next(
        s for s in result.summary.stability if (s.score_id, s.from_wave) == ("ems_total", "1")
    )
    assert (rows[0]["score"], rows[0]["p0"]) == ("Total score", f"{total.r:.2f} (n {total.n})")
    assert [r["score"] for r in rows] == [s.label for s in mood.scores]


def test_sample_table_reads_like_a_table_one(mock_project):
    result = run_catalog(mock_project)
    columns, rows = instruments.sample_table(
        result, result.project.instruments["example_demographics"]
    )
    assert [c["label"] for c in columns[2:]] == ["parent_w1", "parent_w2", "parent_w3"]
    by_label = {(r["item"] or "", r["value"]): r for r in rows}
    age = "How old is your child (in years)?"
    assert by_label[(age, "n")]["d1"] == 127
    assert [r["value"] for r in rows[1:4]] == ["Mean (SD)", "Median", "Range"]
    girls = by_label[("", "Girl")]["d1"]
    assert girls.endswith("%)") and int(girls.split()[0]) > 0
    comment = "Is there anything else about your family's situation you would like us to know?"
    assert by_label[(comment, "Answered")]["d0"] > 0
    assert rows[-1]["value"] == "Answered"
