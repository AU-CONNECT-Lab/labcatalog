import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from labcatalog.gui.files import FILE, FOLDER, listing, patterns
from labcatalog.gui.gate import Gate

TOKEN = "key-for-this-run"


async def page(request):
    return PlainTextResponse("the catalog")


async def socket(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("hello")
    await websocket.close()


@pytest.fixture
def client():
    inner = Starlette(routes=[Route("/", page), WebSocketRoute("/ws", socket)])
    return TestClient(Gate(inner, token=TOKEN, port=8123), base_url="http://127.0.0.1")


def test_without_the_key_nothing_opens(client):
    refused = client.get("/")
    assert refused.status_code == 403 and "printed" in refused.text
    assert client.get("/?token=wrong").status_code == 403
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws") as ws:
        ws.receive_text()


def test_the_link_with_the_key_opens_and_is_remembered(client):
    opened = client.get(f"/?token={TOKEN}")
    assert opened.text == "the catalog"
    assert "HttpOnly" in opened.headers["set-cookie"]
    assert client.cookies.get("labcatalog_8123") == TOKEN
    assert client.get("/").text == "the catalog"
    # The test client sends its websocket to another host name, so the cookie goes by hand.
    remembered = {"cookie": f"labcatalog_8123={TOKEN}"}
    with client.websocket_connect("/ws", headers=remembered) as ws:
        assert ws.receive_text() == "hello"


def test_the_chooser_reads_the_dialog_file_types():
    assert patterns(("PDF files (*.pdf)",)) == ["*.pdf"]
    assert patterns(("CSV files (*.csv;*.tsv;*.txt)",)) == ["*.csv", "*.tsv", "*.txt"]
    assert patterns(()) == []


def test_the_chooser_lists_folders_and_matching_files(tmp_path):
    for name in ("b.csv", "A.CSV", "notes.txt", ".hidden.csv"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / ".git").mkdir()
    folders, files = listing(tmp_path, ["*.csv"], FILE)
    assert [p.name for p in folders] == ["raw"]
    assert [p.name for p in files] == ["A.CSV", "b.csv"]
    assert listing(tmp_path, [], FOLDER) == (folders, [])
