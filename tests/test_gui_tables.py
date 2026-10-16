from pathlib import Path

from labcatalog.bibliography import citation
from labcatalog.browse import build_index, matches
from labcatalog.charts import views
from labcatalog.gui import datasets, instruments, overview
from labcatalog.gui.common import split_location
from labcatalog.pipeline import run_catalog
from labcatalog.stats.cfa import ONE_FACTOR, SUBSCALES, CfaFit
from labcatalog.stats.invariance import InvarianceStep, InvarianceTest


def test_location_splits_off_the_line_number():
    assert split_location("studies/demo_study.yaml:5") == ("studies/demo_study.yaml", 5)
    assert split_location("data/parent_w1.csv") == ("data/parent_w1.csv", None)
    outside = Path.cwd() / "data" / "parent_w1.csv"
    path, line = split_location(f"{outside.as_posix()}:3")
    assert (Path("project") / path, line) == (outside, 3)


def test_wave_table(mock_project):
    result = run_catalog(mock_project)
    _, waves = overview.wave_table(result)
    assert [(w["wave"], w["n_parent"], w["n_child"]) for w in waves] == [
        ("1", 191, 182),
        ("2", 170, 153),
        ("3", 159, 148),
    ]


def test_instrument_list_shows_only_the_matched_datasets(mock_project):
    result = run_catalog(mock_project)
    index = build_index(result.project)
    found = matches(index, {"reporter": {"child"}})
    columns, rows = instruments.list_table(result, found)
    assert [c["label"] for c in columns[-4:-1]] == ["child_w1", "child_w2", "child_w3"]
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {"example_mood", "example_screen_time"}
    screen = by_id["example_screen_time"]
    assert (screen["d0"], screen["d1"], screen["d2"]) == ("", 153, 148)
    assert by_id["example_mood"]["reporters"] == "child"


def test_instrument_list_says_what_each_instrument_lacks(mock_project):
    result = run_catalog(mock_project)
    found = {"example_mood": [], "example_screen_time": []}
    columns, rows = instruments.list_table(result, found)
    assert columns[-1]["label"] == "Missing"
    by_id = {r["id"]: r for r in rows}
    assert by_id["example_mood"]["missing"] == ""
    assert by_id["example_screen_time"]["missing"].startswith("description, scores")
    columns, _ = instruments.list_table(result, {"example_mood": []})
    assert "missing" not in [c["name"] for c in columns]


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
    result = run_catalog(mock_project)
    key = result.project.config.studies["mock_study"].reference
    assert citation(result.project.bibliography, key) == (
        "Mock Family Study Team (2026). Mock Family Study: Waves 1 to 3. Example Data Archive."
    )
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
    columns, rows = instruments.item_total_waves(result, mood, "ems_total")
    assert [c["label"] for c in columns[2:]] == [
        "Wave 1 (α 0.90)",
        "Wave 2 (α 0.91)",
        "Wave 3 (α 0.90)",
    ]
    assert [r["item"] for r in rows] == [f"ems_{i}" for i in range(1, 10)]
    assert all(r["d0"] and r["d2"] for r in rows)
    first = next(t for t in views.summary_of(result, "example_mood.ems_total@child_w1").item_total)
    assert rows[0]["d0"] == f"{first.r:.2f} ({first.alpha_if_deleted:.2f})"
    sadness = next(s for s in mood.scores if s.id == "ems_sadness")
    _, rows = instruments.item_total_waves(result, mood, "ems_sadness")
    assert [r["item"] for r in rows] == sadness.items
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
    assert by_label[(age, "n")]["d1"] == 167
    assert [r["value"] for r in rows[1:4]] == ["Mean (SD)", "Median", "Range"]
    girls = by_label[("", "Girl")]["d1"]
    assert girls.endswith("%)") and int(girls.split()[0]) > 0
    comment = "Is there anything else about your family's situation you would like us to know?"
    assert by_label[(comment, "Answered")]["d0"] > 0
    assert rows[-1]["value"] == "Answered"


def test_factor_tables_show_fit_loadings_and_omega(mock_project):
    result = run_catalog(mock_project)
    mood = result.project.instruments["example_mood"]
    subscales = {
        s.score_id: s.columns
        for s in result.catalog.scores_for("child_w1")
        if s.instrument_id == "example_mood" and s.score_id != "ems_total"
    }
    fits = [
        CfaFit(
            "example_mood",
            "child_w1",
            SUBSCALES,
            subscales,
            110,
            fit={
                "chisq": 23.45,
                "df": 24.0,
                "p": 0.493,
                "cfi": 1.0,
                "tli": 1.0,
                "rmsea": 0.0,
                "srmr": 0.033,
            },
            loadings={("ems_sadness", "ems_2_w1"): 0.81},
            omega={"ems_sadness": 0.87},
        ),
        CfaFit(
            "example_mood",
            "child_w1",
            ONE_FACTOR,
            {"ems_total": ["ems_1_w1"]},
            110,
            problem="improper solution",
        ),
        CfaFit(
            "example_mood",
            "child_w1",
            ONE_FACTOR,
            {"ems_low_positive": ["ems_1_w1"]},
            110,
            fit={"chisq": None, "df": 0.0},
        ),
    ]
    _, rows = instruments.fit_table(mood, fits)
    assert rows[0]["model"] == "Subscales: Sadness, Worry and fatigue, Low positive affect"
    assert (rows[0]["chisq"], rows[0]["p"], rows[0]["cfi"]) == ("23.45 (24)", ".493", "1.00")
    assert rows[1]["problem"] == "improper solution"
    assert rows[2]["problem"].startswith("3 items")
    columns, rows = instruments.loading_table(result, mood, "child_w1", fits)
    assert [c["label"] for c in columns][:3] == ["Variable", "Item", "Total score"]
    sadness = next(r for r in rows if r["column"] == "ems_2_w1")
    assert sadness["s_ems_sadness"] == "0.81"
    assert rows[-1]["column"] == "ω" and rows[-1]["s_ems_sadness"] == "0.87"
    assert instruments.omegas(fits) == {"ems_sadness": 0.87}


def test_invariance_table_shows_each_step_against_the_one_before():
    def fit(df: float, cfi: float, rmsea: float) -> dict:
        return {"chisq": 100.0 + df, "df": df, "cfi": cfi, "rmsea": rmsea, "srmr": 0.05}

    test = InvarianceTest(
        "mock_study",
        "child",
        "example_mood",
        SUBSCALES,
        {},
        {"1": 110, "2": 82},
        steps=[
            InvarianceStep("configural", fit(111, 0.999, 0.010)),
            InvarianceStep("thresholds", fit(120, 0.995, 0.020), 12.79, 9.0, 0.172),
            InvarianceStep("metric", problem="improper solution"),
            InvarianceStep("scalar", fit(132, 0.980, 0.030)),
        ],
    )
    _, rows = instruments.invariance_table(test)
    assert [r["step"] for r in rows] == [
        "Configural",
        "Thresholds",
        "Metric (+ loadings)",
        "Scalar (+ intercepts)",
    ]
    assert (rows[0]["chisq"], rows[0]["diff"], rows[0]["dcfi"]) == ("211.00 (111)", "", "")
    second = rows[1]
    assert (second["diff"], second["p"]) == ("12.79 (9)", ".172")
    assert (second["dcfi"], second["drmsea"]) == ("-0.004", "0.010")
    assert (rows[2]["chisq"], rows[2]["problem"]) == ("", "improper solution")
    assert (rows[3]["dcfi"], rows[3]["diff"]) == ("", "")


def test_score_table_lists_every_wave_under_its_score(mock_project):
    result = run_catalog(mock_project)
    mood = result.project.instruments["example_mood"]
    columns, rows = instruments.score_table(result, mood, [])
    assert "ω" not in [c["label"] for c in columns]
    assert not any(c["sortable"] for c in columns)
    assert len(rows) == 3 * len(mood.scores)
    assert [(r["score"], r["wave"]) for r in rows[:4]] == [
        ("Total score", "Wave 1"),
        ("", "Wave 2"),
        ("", "Wave 3"),
        (mood.scores[1].label, "Wave 1"),
    ]
    total = views.summary_of(result, "example_mood.ems_total@child_w2")
    assert (rows[1]["n"], rows[1]["mean"]) == (total.n_valid, f"{total.mean:.2f}")
    fit = CfaFit("example_mood", "child_w2", ONE_FACTOR, {}, 100, omega={"ems_total": 0.9})
    columns, rows = instruments.score_table(result, mood, [fit])
    assert "ω" in [c["label"] for c in columns]
    assert [r["omega"] for r in rows[:3]] == ["", "0.90", ""]
