from datetime import date

import pytest
from typer.testing import CliRunner

from labcatalog.datalad.freeze import list_freezes
from labcatalog.exceptions import FreezeError
from labcatalog.pipeline import run_freeze

runner = CliRunner()


def test_a_freeze_outside_datalad_writes_only_a_record(mock_project):
    path, record = run_freeze(mock_project, "pilot", None)
    assert path == mock_project / "freezes" / f"{date.today()}_pilot.json"
    assert record.tag is None
    assert record.participants["parent_w1"] == 191
    assert {f.dataset for f in record.manifest.files} >= {"parent_w1", "child_w3"}
    assert record.manifest.datalad == []
    [listed] = list_freezes(mock_project)
    assert listed == record


def test_freeze_names_are_checked(mock_project):
    with pytest.raises(FreezeError, match="cannot name a freeze"):
        run_freeze(mock_project, "my freeze", None)
    run_freeze(mock_project, "pilot", None)
    with pytest.raises(FreezeError, match="already a freeze named pilot"):
        run_freeze(mock_project, "pilot", None)

