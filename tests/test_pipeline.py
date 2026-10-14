from labcatalog.pipeline import run_catalog, run_check


def test_catalog_has_everything_the_gui_shows(mock_project):
    result = run_catalog(mock_project)
    assert result.project.config.project.name == "Mock Family Study Catalog"
    assert result.report.issues == run_check(mock_project).issues
    assert {d.dataset for d in result.summary.datasets} == {
        "parent_w1",
        "parent_w2",
        "child_w1",
        "child_w2",
    }
    assert set(result.snippets) == {s.key for s in result.catalog.scores}
    assert len(result.manifest.files) == 4


def test_metadata_errors_return_only_the_report(mock_project):
    config = mock_project / "labcatalog.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            "reporters: [parent, child]", "reporters: [parent]"
        ),
        encoding="utf-8",
    )
    result = run_catalog(mock_project)
    assert result.report.has_errors()
    assert result.project is None
    assert result.summary is None
