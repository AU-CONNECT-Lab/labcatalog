from pathlib import Path

from labcatalog import defaults


def serve(
    site_dir: Path, references_root: Path | None = None, port: int = defaults.PREVIEW_PORT
) -> None:
    raise NotImplementedError
