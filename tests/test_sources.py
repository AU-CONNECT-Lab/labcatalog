import pandas as pd
import pytest

from labcatalog.exceptions import DataSourceError
from labcatalog.project import load_project
from labcatalog.sources import load_datasets


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_loads_every_dataset_as_text(mock_project):
    datasets = load_datasets(load_project(mock_project))
    assert {name: len(d.frame) for name, d in datasets.items()} == {
        "parent_w1": 116,
        "parent_w2": 38,
        "child_w1": 111,
        "child_w2": 34,
    }
    frame = datasets["parent_w1"].frame
    assert all(pd.api.types.is_string_dtype(dtype) for dtype in frame.dtypes)
    assert "-99" in set(frame["eps_1_w1"])
    assert "" in set(frame["eps_1_w1"])


def test_ids_are_normalized_and_families_derived(mock_project):
    parent = load_datasets(load_project(mock_project))["parent_w1"]
    changed = parent.raw_ids != parent.frame["pid"]
    assert parent.raw_ids[changed].tolist() == [" 1031P"]
    assert parent.frame.loc[changed, "pid"].tolist() == ["1031P"]
    assert parent.family.iloc[0] == parent.frame["pid"].iloc[0][:4]


def test_exclusions_by_person_and_by_family(mock_project):
    (mock_project / "withdrawn.csv").write_text("id,reason\n1031P,withdrew\n1003,family withdrew\n")
    edit(
        mock_project / "labcatalog.yaml",
        "custom_fields:",
        "exclusions: withdrawn.csv\n\ncustom_fields:",
    )
    datasets = load_datasets(load_project(mock_project))
    assert datasets["parent_w1"].n_excluded == 2
    assert "1031P" not in set(datasets["parent_w1"].frame["pid"])
    assert "1003C" not in set(datasets["child_w1"].frame["pid"])


def test_missing_data_file(mock_project):
    (mock_project / "data" / "child_w2.csv").unlink()
    with pytest.raises(DataSourceError, match="child_w2: data file not found"):
        load_datasets(load_project(mock_project))


def test_data_file_not_saved_as_utf8(mock_project):
    (mock_project / "data" / "child_w2.csv").write_bytes(
        "pid,note\n1001C,caf\xe9\n".encode("cp1252")
    )
    with pytest.raises(DataSourceError, match="CSV UTF-8"):
        load_datasets(load_project(mock_project))


def test_missing_id_column(mock_project):
    edit(mock_project / "labcatalog.yaml", "id_column: pid", "id_column: participant")
    with pytest.raises(DataSourceError, match="no ID column 'participant'"):
        load_datasets(load_project(mock_project))
