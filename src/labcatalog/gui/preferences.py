import json
import os
import sys
from pathlib import Path

FILENAME = "gui.json"
PALETTE = "palette"
RSCRIPT = "rscript"
LLM_PROVIDER = "llm_provider"
LLM_MODEL = "llm_model"
LLM_URL = "llm_url"
DEFAULT_LLM_PROVIDER = "anthropic"
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
