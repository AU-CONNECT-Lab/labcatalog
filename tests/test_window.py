import asyncio
from pathlib import Path

import pytest
from nicegui import core, ui
from nicegui.client import Client

from labcatalog import defaults
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import app, common, files, preferences, shared


@pytest.fixture(autouse=True)
def offline(tmp_path: Path, monkeypatch) -> None:
    # A page built without a browser or a server, with its own settings folder.
    monkeypatch.setattr(preferences, "folder", lambda: tmp_path / "settings")
    monkeypatch.setattr(core, "loop", None)
    monkeypatch.setattr(shared, "PROJECTS", {})


def on_page(work) -> object:
    async def main():
        core.loop = asyncio.get_running_loop()
        client = Client(ui.page("/"), request=None)
        with client:
            return await work(client)

    return asyncio.run(main())


def test_a_project_whose_data_cannot_be_read_stays_open_with_the_error(mock_project):
    (mock_project / "data" / "parent_w1.csv").unlink()

    async def work(client):
        window = app.Window()
        window.build()
        await window.load(mock_project)
        return window

    window = on_page(work)
    assert window.root == mock_project and window.result is None
    assert "parent_w1.csv" in window.error
    # Watched all the same, so the file put back shows as a change on disk.
    assert mock_project / defaults.CONFIG_FILENAME in window.times


def test_opening_shares_another_windows_build_and_other_loads_read_again(mock_project, monkeypatch):
    asked = []

    def catalog(root, again=False):
        asked.append(again)
        raise LabCatalogError("stop here")

    monkeypatch.setattr(shared, "catalog", catalog)

    async def work(client):
        window = app.Window()
        window.build()
        await window.open_project(mock_project)
        await window.reload()

    on_page(work)
    assert asked == [False, True]


def test_a_callbacks_own_none_comes_back():
    async def work(client):
        return await common.computed(lambda: None), await common.computed(lambda: 0)

    assert on_page(work) == (None, 0)


def test_serving_the_chooser_starts_inside_the_folder_of_projects(tmp_path, monkeypatch):
    served = tmp_path / "served"
    (served / "lab").mkdir(parents=True)
    monkeypatch.setattr(common, "serving", served.resolve())
    monkeypatch.setattr(common, "native", False)

    async def work(client):
        task = asyncio.create_task(choose(client, tmp_path))
        await asyncio.sleep(0.1)
        choose_button = next(
            e for e in client.elements.values() if isinstance(e, ui.button) and e.text == "Choose"
        )
        for listener in choose_button._event_listeners.values():
            listener.handler(None)
        return await task

    assert on_page(work) == served.resolve()


async def choose(client: Client, start: Path) -> Path | None:
    with client.layout:
        return await files.choose_path(files.FOLDER, start=start)
