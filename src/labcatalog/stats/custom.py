import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog.exceptions import RError
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import analysis
from labcatalog.stats.analysis import ITEM_PREFIX, STUDY_KEY, first_key
from labcatalog.stats.analysis_script import (
    DATA_FILE,
    PERSON_ID,
    SCORE,
    AnalysisData,
    Variable,
    link_name,
)
from labcatalog.stats.rbridge import r_turn, run_process

NO_R = "R scripts run in R: set the path to Rscript on the Settings page."
SCRIPT = {"r": "analysis.R", "python": "analysis.py"}


@dataclass
class Ran:
    ok: bool
    # What the script printed, then what it reported as errors or warnings.
    output: str
    # The files it wrote beside the data, by name.
    files: dict[str, bytes] = field(default_factory=dict)


def analysis_frame(
    result: CatalogResult, sample: analysis.Sample, keys: list[str]
) -> tuple[pd.DataFrame, list[Variable], AnalysisData]:
    # Scores come with their items, so a script can model them too.
    data = AnalysisData(result, sample)
    variables = [
        data.item(k) if k.startswith(ITEM_PREFIX) or k == STUDY_KEY else data.score(k, items=True)
        for k in keys
    ]
    return data.frame(), variables, data


def columns_text(
    result: CatalogResult,
    sample: analysis.Sample,
    frame: pd.DataFrame,
    variables: list[Variable],
) -> str:
    def counted(column: str) -> str:
        return str(int(frame[column].notna().sum()))

    lines = [
        f"{DATA_FILE}: {len(frame)} rows, one for each person.",
        "Its columns (column | what it holds | values | people with a value):",
        f"{link_name(result)} | the ID that links a person's rows across the files | text |",
    ]
    if PERSON_ID in frame:
        lines.append(
            f"{PERSON_ID} | the person's own ID, where several share the one above | text |"
        )
    if STUDY_KEY in frame:
        studies = ", ".join(
            f"{code:g} = {label}" for code, label in analysis.study_options(result, sample)
        )
        lines.append(f"{STUDY_KEY} | the study the person is in | {studies} |")
    for name in sample.datasets:
        lines.append(f"in_{name} | 1 if the person is in the dataset {name}, else 0 | 0 or 1 |")
    described: set[str] = set()
    for v in variables:
        if v.column in described:
            continue
        described.add(v.column)
        lines.append(f"{v.column} | {what(result, v)} | {values_text(v)} | {counted(v.column)}")
        for column in v.items:
            if column not in described:
                described.add(column)
                lines.append(
                    f"{column} | an item of {v.label}, reversed where the scale says so | "
                    f"number | {counted(column)}"
                )
    return "\n".join(lines)


def what(result: CatalogResult, v: Variable) -> str:
    if v.kind != SCORE:
        return f"{v.label} ({v.dataset})" if v.dataset else v.label
    score = next(s for s in result.catalog.scores if s.key == first_key(v.key))
    instrument = result.project.instruments[score.instrument_id]
    definition = next(s for s in instrument.scores if s.id == score.score_id)
    return f"the score {v.label} ({v.dataset}), the {definition.method} of its items"


def values_text(v: Variable) -> str:
    if v.options:
        return ", ".join(f"{value:g} = {label}" for value, label in v.options)
    return "number"


def run_script(
    language: str,
    script: str,
    frame: pd.DataFrame,
    rscript: str | None,
    started: Callable[[subprocess.Popen], None] | None = None,
) -> Ran:
    # In a folder of its own beside the data, so whatever it writes can be shown and saved.
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        frame.to_csv(folder / DATA_FILE, index=False)
        path = folder / SCRIPT[language]
        path.write_text(script, encoding="utf-8")
        if language == "r":
            if not rscript:
                raise RError(NO_R)
            try:
                with r_turn():
                    done = run_process([rscript, path.name], folder, started)
            except OSError:
                raise RError(
                    f"Rscript not found at {rscript}; check the path on the Settings page"
                ) from None
        else:
            # -I keeps the user's own settings out; -X utf8 keeps printed text readable on Windows.
            done = run_process([sys.executable, "-I", "-X", "utf8", path.name], folder, started)
        files = {
            p.name: p.read_bytes()
            for p in sorted(folder.iterdir())
            if p.is_file() and p.name not in (DATA_FILE, path.name)
        }
    output = "\n".join(part.rstrip() for part in (done.stdout, done.stderr) if part.strip())
    return Ran(done.returncode == 0, output, files)
