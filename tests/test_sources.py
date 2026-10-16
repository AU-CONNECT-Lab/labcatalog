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
        "parent_w1": 191,
        "parent_w2": 170,
        "parent_w3": 160,
        "child_w1": 182,
        "child_w2": 153,
        "child_w3": 148,
    }
    frame = datasets["parent_w1"].frame
    assert all(pd.api.types.is_string_dtype(dtype) for dtype in frame.dtypes)
    assert "-97" in set(frame["eps_1_w1"])
    assert "" in set(frame["eps_1_w1"])


def test_ids_are_read_as_is_and_groups_derived(mock_project):
    parent = load_datasets(load_project(mock_project))["parent_w1"]
    assert " 1031P" in set(parent.frame["pid"])
    assert parent.group.iloc[0] == parent.frame["pid"].iloc[0][:4]


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
