import pandas as pd
import pytest

from labcatalog.metadata.validate import validate_project
from labcatalog.pipeline import run_catalog
from labcatalog.project import load_project

INSTRUMENT = "instruments/example_parent_stress.yaml"
SCRIPTED = "  - {id: eps_t, label: T score, method: script}\n"
KEY = "example_parent_stress.eps_t@parent_w1"


def score_by_script(root, scores_file: str | None = "data/parent_w1_scores.csv") -> None:
    path = root / INSTRUMENT
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("references:\n", SCRIPTED + "references:\n", 1), encoding="utf-8")
    if scores_file:
        config = root / "labcatalog.yaml"
        entry = "path: data/parent_w1.csv,"
        config.write_text(
            config.read_text(encoding="utf-8").replace(entry, f"{entry} scores: {scores_file},", 1),
            encoding="utf-8",
        )


def write_scores(root, rows: dict[str, str], **columns: list[str]) -> None:
    frame = pd.DataFrame({"pid": list(rows), "eps_t": list(rows.values()), **columns})
    frame.to_csv(root / "data" / "parent_w1_scores.csv", index=False)


def issues_of(result, code: str) -> list[str]:
    # Only parent_w1 has a scores file; the other waves' messages are about that.
    return [i.message for i in result.report.issues if i.code == code and "parent_w1" in i.message]


def test_a_script_score_is_read_from_the_scores_file_by_id(mock_project):
    score_by_script(mock_project)
    write_scores(mock_project, {"1001P": "51.5", "1002P": "", "9999P": "60"})
    assert not [i for i in validate_project(load_project(mock_project)) if i.level == "error"]
    result = run_catalog(mock_project)
    loaded = result.datasets["parent_w1"]
    values = result.scores["parent_w1"][KEY]
    ids = loaded.frame[loaded.id_column]
    assert values[ids == "1001P"].tolist() == [51.5]
    assert values[ids == "1002P"].isna().all()
    assert values.notna().sum() == 1
    [stray] = issues_of(result, "scores_unmatched")
    assert "1 ID(s) of data/parent_w1_scores.csv are not in the data: 9999P" in stray
    summary = next(s for s in result.summary.scores if s.key == KEY)
    assert summary.n_valid == 1 and summary.alpha is None


def test_a_missing_scores_file_or_column_is_a_warning(mock_project):
    score_by_script(mock_project)
    result = run_catalog(mock_project)
    assert issues_of(result, "scores_missing") == [
        "parent_w1: the scores file data/parent_w1_scores.csv is not there yet; run the step "
        "that writes it"
    ]
    assert result.scores["parent_w1"][KEY].isna().all()
    pd.DataFrame({"pid": ["1001P"], "other": ["1"]}).to_csv(
        mock_project / "data" / "parent_w1_scores.csv", index=False
    )
    [missing] = issues_of(run_catalog(mock_project), "scores_missing")
    assert missing == f"{KEY}: the scores file data/parent_w1_scores.csv has no column eps_t"


def test_without_a_scores_file_a_script_score_says_so(mock_project):
    score_by_script(mock_project, None)
    [missing] = issues_of(run_catalog(mock_project), "scores_missing")
    assert missing == f"{KEY}: computed by a script, but parent_w1 names no scores file"


def test_a_scores_file_column_for_a_summed_score_is_held_to_labcatalogs(mock_project):
    score_by_script(mock_project)
    result = run_catalog(mock_project)
    loaded = result.datasets["parent_w1"]
    ids = loaded.frame[loaded.id_column]
    computed = result.scores["parent_w1"]["example_parent_stress.eps_strain@parent_w1"]
    found = {
        pid: f"{value:.2f}" for pid, value in zip(ids, computed, strict=True) if pd.notna(value)
    }
    first = next(iter(found))
    strain = dict(found, **{first: "9.99"})
    write_scores(mock_project, dict.fromkeys(strain, "50"), eps_strain=list(strain.values()))
    [mismatch] = issues_of(run_catalog(mock_project), "score_mismatch")
    assert mismatch.startswith(
        "example_parent_stress.eps_strain@parent_w1: 1 row(s) differ from "
        "data/parent_w1_scores.csv, eps_strain"
    )


@pytest.mark.parametrize("method", ["sum", "mean"])
def test_a_summed_or_averaged_score_needs_items(mock_project, method):
    path = mock_project / INSTRUMENT
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "references:\n", f"  - {{id: none, label: None, method: {method}}}\nreferences:\n"
        ),
        encoding="utf-8",
    )
    messages = [i.message for i in validate_project(load_project(mock_project))]
    assert f"scores[4] (none).items: list the items it is the {method} of" in messages
