from datetime import datetime
from pathlib import Path

from labcatalog import defaults
from labcatalog.data.manifest import Manifest


def write_output(root: Path, name: str, files: dict[str, bytes], manifest: Manifest) -> Path:
    base = root / defaults.OUTPUTS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{name}"
    folder = base
    # Two saves within one second get _2, _3 rather than failing.
    n = 1
    while folder.exists():
        n += 1
        folder = base.with_name(f"{base.name}_{n}")
    folder.mkdir(parents=True)
    for filename, content in files.items():
        (folder / filename).write_bytes(content)
    # Which data files, at which checksums, the saved numbers came from.
    (folder / defaults.MANIFEST_FILENAME).write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return folder
