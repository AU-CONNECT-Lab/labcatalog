from pathlib import Path

import pytest

from labcatalog.exceptions import MetadataError
from labcatalog.metadata.bibliography import citation, load_bibliography
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
