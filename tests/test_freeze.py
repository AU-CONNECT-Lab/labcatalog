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


def test_a_freeze_name_is_one_git_takes_as_a_tag_and_is_matched_whole(mock_project):
    for name in ["v1.", "a..b", "final.lock"]:
        with pytest.raises(FreezeError, match="cannot name a freeze"):
            run_freeze(mock_project, name, None)
    run_freeze(mock_project, "pilot_b", None)
    run_freeze(mock_project, "b", None)
    assert {f.name for f in list_freezes(mock_project)} == {"pilot_b", "b"}


def test_a_freeze_record_without_its_content_says_how_to_get_it(mock_project):
    folder = mock_project / "freezes"
    folder.mkdir()
    (folder / "2026-01-01_pilot.json").write_text("/annex/objects/SHA256E-s10--ab.json\n")
    with pytest.raises(FreezeError, match="not on this computer; get it with: datalad get"):
        list_freezes(mock_project)
