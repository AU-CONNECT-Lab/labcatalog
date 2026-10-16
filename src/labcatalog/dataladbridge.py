import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from labcatalog.exceptions import DataladError

INSTALL = "uv tool install git-annex and uv tool install datalad"


@dataclass
class DataladStatus:
    datalad: str
    annex: str


def use_folder(datalad: str) -> None:
    # Inside a dataset git itself runs git-annex, so every git call needs DataLad's folder on PATH.
    folder = str(Path(datalad).parent)
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if folder not in paths:
        os.environ["PATH"] = os.pathsep.join([folder, *paths])


def datalad_status(datalad: str) -> DataladStatus:
    version = run_datalad(datalad, ["--version"]).strip()
    try:
        annex = subprocess.run(
            ["git", "annex", "version", "--raw"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise DataladError(
            f"{version}, but git-annex was not found; install it, for example with: "
            "uv tool install git-annex"
        ) from None
    return DataladStatus(version, annex)


def run_datalad(datalad: str, args: list[str], cwd: Path | None = None) -> str:
    try:
        done = subprocess.run(
            [datalad, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        raise DataladError(
            f"DataLad not found at {datalad}; check the path on the Settings page"
        ) from None
    if done.returncode != 0:
        output = (done.stderr or done.stdout).strip()
        raise DataladError(f"datalad {args[0]} failed: {output[-500:]}")
    return done.stdout
