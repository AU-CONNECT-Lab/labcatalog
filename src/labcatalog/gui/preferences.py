import json
import os
import secrets
import sys
from collections.abc import MutableMapping
from pathlib import Path

from labcatalog import own_python

FILENAME = "gui.json"
PALETTE = "palette"
APPEARANCE = "appearance"
RSCRIPT = "rscript"
MPLUS = "mplus"
PYTHON = "python"
BOOTSTRAP_WORKERS = "bootstrap_workers"
R_AT_ONCE = "r_at_once"
DATALAD = "datalad"
LAST_PROJECT = "last_project"
# The study each project was last narrowed to, by its folder.
STUDY_SCOPE = "study_scope"
LLM_URL = "llm_url"
TABLE_FORMAT = "table_format"
RICH = "rich"
LATEX = "latex"
# The name a person gives when one labcatalog serves several people.
WHO = "who"
# Each person's own; kept per browser when one labcatalog serves several people.
PERSONAL = (PALETTE, APPEARANCE, LAST_PROJECT, STUDY_SCOPE, TABLE_FORMAT, WHO)
# Signs the browsers' cookies, kept so that people's own settings outlast a restart.
SERVER_SECRET = "server_secret"


def folder() -> Path:
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "labcatalog"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "labcatalog"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "labcatalog"


def load() -> dict:
    path = folder() / FILENAME
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def save(changes: dict) -> None:
    path = folder() / FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**load(), **changes}, indent=2), encoding="utf-8")


def no_browser() -> MutableMapping | None:
    return None


# Where each person's own settings go instead of this computer's file; serving points it at the
# browser's storage on the server.
browser = no_browser


def mine() -> dict:
    store = browser()
    return load() if store is None else dict(store)


def save_mine(changes: dict) -> None:
    store = browser()
    if store is None:
        save(changes)
    else:
        store.update(changes)


def server_secret() -> str:
    found = load().get(SERVER_SECRET)
    if not found:
        found = secrets.token_urlsafe(32)
        save({SERVER_SECRET: found})
    return found


def python() -> str:
    # Unset, labcatalog's own Python runs the scripts, in the Windows program too.
    return load().get(PYTHON) or sys.executable


def step_python() -> str | None:
    # The Python a prepare step's python command gets; installed with pip, the one on PATH.
    return load().get(PYTHON) or (sys.executable if own_python.frozen() else None)
