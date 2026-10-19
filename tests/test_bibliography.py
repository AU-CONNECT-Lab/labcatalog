from pathlib import Path

import pytest

from labcatalog.exceptions import MetadataError
from labcatalog.metadata.bibliography import (
    add_entries,
    citation,
    load_bibliography,
    pasted_entries,
)
from labcatalog.project import load_project

BIB = r"""
@string{jdm = "Journal of Demonstration Measures"}

@article{example2019,
  author = {Example, Anna and Sample, B{\"o}rje},
  title = {Development of the {Example} Mood Scale},
  journal = jdm # " (Series " # {B} # ")",
  year = 2019,
  doi = {10.0000/demo.2019},
}

@techreport{who2020,
  author = {{World Health Organization} and Ludwig van Beethoven and Third, C.},
  title = {Is this a manual?},
  date = {2020-05-01},
}
"""


def load(tmp_path: Path, text: str) -> tuple[dict, list]:
    path = tmp_path / "references.bib"
    path.write_text(text, encoding="utf-8")
    issues: list = []
    return load_bibliography(path, tmp_path, issues), issues


def test_fields_are_evaluated_and_decoded(tmp_path):
    bibliography, issues = load(tmp_path, BIB)
    assert issues == []
    entry = bibliography["example2019"]
    assert entry["journal"] == "Journal of Demonstration Measures (Series B)"
    assert entry["year"] == "2019"
    assert entry["doi"] == "10.0000/demo.2019"
    assert "Börje" in entry["author"]


def test_citation_names_authors_year_title_and_venue(tmp_path):
    bibliography, _ = load(tmp_path, BIB)
    assert citation(bibliography, "example2019") == (
        "Example & Sample (2019). Development of the Example Mood Scale. "
        "Journal of Demonstration Measures (Series B)."
    )
    assert citation(bibliography, "who2020") == (
        "World Health Organization et al. (2020). Is this a manual?"
    )
    assert citation(bibliography, "unknown2000") == "unknown2000"


def test_broken_and_repeated_entries_are_errors_with_lines(tmp_path):
    text = (
        BIB
        + "\n@article{example2019,\n  title = {again},\n}\n\n@article{broken,\n  title = {open\n"
    )
    bibliography, issues = load(tmp_path, text)
    assert [(i.code, i.location) for i in issues] == [
        ("duplicate_id", "references.bib:18"),
        ("bib_syntax", "references.bib:22"),
    ]
    assert bibliography["example2019"]["title"] == "Development of the {Example} Mood Scale"


def test_project_loads_the_bib_from_the_references_root(mock_project):
    project = load_project(mock_project)
    assert set(project.bibliography) == {
        "mockstudy2026",
        "example2019",
        "sample2017",
        "demo2021",
        "trial2020",
    }


def test_a_broken_bib_stops_the_project_from_loading(mock_project):
    with (mock_project / "references" / "references.bib").open("a", encoding="utf-8") as file:
        file.write("\n@article{broken,\n  title = {open\n")
    with pytest.raises(MetadataError) as err:
        load_project(mock_project)
    [issue] = err.value.issues
    assert issue.code == "bib_syntax"
    assert issue.location.startswith("references/references.bib:")


PASTED = """@article{smith2020,
  title = {The {Big} Study},
  author = {Smith, Jo},
  year = {2020}
}

@book{example2019, title = {Already there}}
@book{smith2020, title = {Twice}}
"""


def test_pasted_entries_say_which_keys_are_new(mock_project):
    project = load_project(mock_project)
    found, issues = pasted_entries(PASTED, project.bibliography)
    assert [(e.key, e.title, e.taken) for e in found] == [
        ("smith2020", "The Big Study", False),
        ("example2019", "Already there", True),
    ]
    assert found[0].text.startswith("@article{smith2020,") and found[0].text.endswith("}")
    assert [i.code for i in issues] == ["duplicate_id"]


def test_added_entries_go_at_the_end_in_the_files_line_endings(mock_project):
    path = mock_project / "references" / "references.bib"
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    before = path.read_bytes()
    found, _ = pasted_entries(PASTED, load_project(mock_project).bibliography)
    assert add_entries(path, found) == ["smith2020"]
    after = path.read_bytes()
    assert after.startswith(before.rstrip(b"\r\n")) and b"\n" not in after.replace(b"\r\n", b"")
    assert "smith2020" in load_project(mock_project).bibliography
    # Pasting the same again adds nothing.
    assert add_entries(path, found) == []


def test_a_new_bib_is_made_when_there_is_none(tmp_path):
    found, _ = pasted_entries(PASTED, {})
    path = tmp_path / "refs" / "references.bib"
    assert add_entries(path, found) == ["smith2020", "example2019"]
    assert set(load_bibliography(path, tmp_path, [])) == {"smith2020", "example2019"}
