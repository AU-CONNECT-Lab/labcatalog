from datetime import datetime
from pathlib import Path

import pandas as pd

from labcatalog import defaults
from labcatalog.manifest import Manifest


def write_output(root: Path, name: str, files: dict[str, bytes], manifest: Manifest) -> Path:
    folder = root / defaults.OUTPUTS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{name}"
    folder.mkdir(parents=True)
    for filename, content in files.items():
        (folder / filename).write_bytes(content)
    # Which data files, at which checksums, the saved numbers came from.
    (folder / defaults.MANIFEST_FILENAME).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return folder


def table_csv(columns: list[dict], rows: list[dict]) -> bytes:
    frame = pd.DataFrame(rows, columns=[c["name"] for c in columns])
    frame.columns = [c["label"] for c in columns]
    # The byte order mark lets Excel read the file as UTF-8.
    return ("﻿" + frame.to_csv(index=False)).encode("utf-8")
