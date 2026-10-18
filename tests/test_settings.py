from labcatalog.gui import common, preferences
from labcatalog.project import load_project


def test_the_open_project_sets_decimals_and_the_model_and_the_computer_its_server(
    mock_project, monkeypatch, tmp_path
):
    monkeypatch.setattr(preferences, "folder", lambda: tmp_path / "settings")
    preferences.save({preferences.LLM_URL: "http://localhost:11434/v1"})
    config = load_project(mock_project).config
    config.stats.decimals = 3
    config.llm.provider, config.llm.model = "local", "qwen3"
    common.use_project(config)
    assert common.fmt(0.5) == "0.500" and common.model_set()
    assert common.llm_choice() == ("local", "qwen3", "http://localhost:11434/v1")
    common.use_project(None)
    assert common.fmt(0.5) == "0.50" and not common.model_set()
