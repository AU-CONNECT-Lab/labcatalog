import json
import os
import sys
from pathlib import Path

FILENAME = "gui.json"
PALETTE = "palette"
APPEARANCE = "appearance"
RSCRIPT = "rscript"
MPLUS = "mplus"
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
