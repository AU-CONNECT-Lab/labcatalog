from labcatalog.gui import example


def test_a_copy_of_an_example_that_has_changed_since_is_outdated(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    folder = example.example_copy()
    assert not example.outdated(folder)
    assert not example.outdated(tmp_path) and not example.outdated(None)
    (folder / example.MARK).write_text("an older example", encoding="utf-8")
    assert example.outdated(folder)
    (folder / example.MARK).unlink()
    assert example.outdated(folder)
    assert not example.outdated(example.reset_example())
