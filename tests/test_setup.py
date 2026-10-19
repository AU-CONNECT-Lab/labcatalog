from labcatalog.gui import setup
from labcatalog.pipeline import run_catalog

EXTRA = (
    "  - {name: extra_w1, modality: questionnaire, study: mock_study, wave: 1, "
    "reporter: child, source: csv, path: data/child_w1.csv}\n"
)


def test_the_steps_count_drafts_steps_to_run_and_files_to_link(mock_project):
    assert list(setup.STEPS) == [setup.CODEBOOK, setup.DATA, setup.IDS]
    counts = setup.to_do(run_catalog(mock_project))
    assert counts[setup.CODEBOOK] == ""
    (mock_project / "drafts").mkdir(exist_ok=True)
    (mock_project / "drafts" / "new_scale.yaml").write_text("id: new_scale\n", encoding="utf-8")
    config = mock_project / "labcatalog.yaml"
    entry = "  - {name: child_w1,"
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace(entry, EXTRA + entry, 1), encoding="utf-8")
    counts = setup.to_do(run_catalog(mock_project))
    assert counts[setup.CODEBOOK] == "1 drafts"
    assert counts[setup.DATA].endswith("1 to link")
