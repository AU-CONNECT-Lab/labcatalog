import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from labcatalog import schema
from labcatalog.exceptions import LabCatalogError, MplusError, RError
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import analysis, mplus
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
NO_MPLUS = "Mplus inputs run in Mplus: set the path to Mplus on the Settings page."
NO_PYTHON = "Python scripts run in Python: set the path to Python on the Settings page."
MPLUS = "mplus"
SCRIPT = {"r": "analysis.R", "python": "analysis.py", MPLUS: "analysis.inp"}
MPLUS_DATA = "analysis_data.dat"
MPLUS_OUT = "analysis.out"
# Mplus names have at most eight characters and start with a letter.
MPLUS_NAME = 8
PYTHON_PACKAGES = ("pandas", "numpy", "scipy", "statsmodels", "semopy", "matplotlib")
PYTHON_CHECK = (
    "import importlib.util, sys; print(sys.version.split()[0]); "
    "[print(p) for p in {packages} if importlib.util.find_spec(p) is None]"
)


@dataclass
class PythonStatus:
    version: str
    missing: list[str]


@dataclass
class Ran:
    ok: bool
    # What the script printed, then what it reported as errors or warnings; Mplus's output.
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
    language: str = "r",
) -> str:
    names = short_names(list(frame.columns)) if language == MPLUS else {}
    ids = "a number for each ID" if names else "text"

    def line(column: str, held: str, values: str, counted: bool = True) -> str:
        shown = f"{names[column]} ({column})" if names else column
        count = str(int(frame[column].notna().sum())) if counted else ""
        return f"{shown} | {held} | {values} | {count}"

    data_file = MPLUS_DATA if names else DATA_FILE
    lines = [
        f"{data_file}: {len(frame)} rows, one for each person.",
        "Its columns (column | what it holds | values | people with a value):",
        line(link_name(result), "the ID that links a person's rows across the files", ids, False),
    ]
    if PERSON_ID in frame:
        held = "the person's own ID, where several share the one above"
        lines.append(line(PERSON_ID, held, ids, False))
    if STUDY_KEY in frame:
        studies = ", ".join(
            f"{code:g} = {label}" for code, label in analysis.study_options(result, sample)
        )
        lines.append(line(STUDY_KEY, "the study the person is in", studies, False))
    for name in sample.datasets:
        held = f"1 if the person is in the dataset {name}, else 0"
        lines.append(line(f"in_{name}", held, "0 or 1", False))
    described: set[str] = set()
    for v in variables:
        if v.column in described:
            continue
        described.add(v.column)
        lines.append(line(v.column, what(result, v), values_text(v)))
        for column in v.items:
            if column not in described:
                described.add(column)
                held = f"an item of {v.label}, reversed where the scale says so"
                lines.append(line(column, held, "number"))
    return "\n".join(lines)


def what(result: CatalogResult, v: Variable) -> str:
    if v.kind != SCORE:
        return f"{v.label} ({v.dataset})" if v.dataset else v.label
    score = next(s for s in result.catalog.scores if s.key == first_key(v.key))
    instrument = result.project.instruments[score.instrument_id]
    definition = next(s for s in instrument.scores if s.id == score.score_id)
    how = (
        "computed by a script"
        if definition.method == schema.SCRIPT
        else f"the {definition.method} of its items"
    )
    return f"the score {v.label} ({v.dataset}), {how}"


def values_text(v: Variable) -> str:
    if v.options:
        return ", ".join(f"{value:g} = {label}" for value, label in v.options)
    return "number"


def short_names(columns: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    taken: set[str] = set()
    for column in columns:
        base = re.sub(r"[^A-Za-z0-9_]", "_", column)
        base = (base if base[:1].isalpha() else f"v{base}")[:MPLUS_NAME]
        name, n = base, 1
        while name.lower() in taken:
            n += 1
            name = f"{base[: MPLUS_NAME - len(str(n))]}{n}"
        taken.add(name.lower())
        found[column] = name
    return found


def mplus_data(frame: pd.DataFrame) -> pd.DataFrame:
    # Mplus reads numbers only, so each ID becomes a number of its own.
    data = frame.copy()
    for column in data.columns:
        if not pd.api.types.is_numeric_dtype(data[column]):
            codes = pd.Series(pd.factorize(data[column].replace("", None))[0] + 1, index=data.index)
            data[column] = codes.where(codes > 0)
    return data


def mplus_start(frame: pd.DataFrame, title: str) -> str:
    names = short_names(list(frame.columns))
    lines = [
        f"TITLE: {' '.join(title.split())[: mplus.WIDTH - 7]}",
        *(f"! {short} = {column}"[: mplus.WIDTH] for column, short in names.items()),
        f"DATA: FILE = {MPLUS_DATA};",
        "VARIABLE:",
        *mplus.statement(f"NAMES = {' '.join(names.values())}"),
        f"  MISSING = ALL ({mplus.MISSING});",
    ]
    return "\n".join(lines) + "\n"


def data_files(language: str, frame: pd.DataFrame) -> dict[str, str]:
    if language == MPLUS:
        return {MPLUS_DATA: mplus.data_text(mplus_data(frame))}
    return {DATA_FILE: frame.to_csv(index=False)}


def run_script(
    language: str,
    script: str,
    frame: pd.DataFrame,
    program: str | None,
    started: Callable[[subprocess.Popen], None] | None = None,
) -> Ran:
    # program is the Rscript or Mplus the language needs.
    # In a folder of its own beside the data, so whatever it writes can be shown and saved.
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        data = data_files(language, frame)
        for name, text in data.items():
            (folder / name).write_text(text, encoding="utf-8")
        path = folder / SCRIPT[language]
        path.write_text(script, encoding="utf-8")
        if language == MPLUS:
            return run_mplus(program, folder, path, started)
        if language == "r":
            if not program:
                raise RError(NO_R)
            try:
                with r_turn():
                    done = run_process([program, path.name], folder, started)
            except OSError:
                raise RError(
                    f"Rscript not found at {program}; check the path on the Settings page"
                ) from None
        else:
            done = run_python(program, path, folder, started)
        files = written(folder, {*data, path.name})
    output = "\n".join(part.rstrip() for part in (done.stdout, done.stderr) if part.strip())
    return Ran(done.returncode == 0, output, files)


def run_mplus(
    program: str | None,
    folder: Path,
    path: Path,
    started: Callable[[subprocess.Popen], None] | None,
) -> Ran:
    if not program:
        raise MplusError(NO_MPLUS)
    try:
        done = run_process([program, path.name, MPLUS_OUT], folder, started)
    except OSError:
        raise MplusError(
            f"Mplus not found at {program}; check the path on the Settings page"
        ) from None
    out = folder / MPLUS_OUT
    if not out.is_file():
        printed = (done.stdout + done.stderr).strip()
        return Ran(False, printed or "Mplus wrote no output.")
    output = out.read_text(encoding="utf-8", errors="replace")
    files = written(folder, {MPLUS_DATA, path.name, MPLUS_OUT})
    return Ran(done.returncode == 0 and "*** ERROR" not in output, output, files)


def run_python(
    program: str | None,
    path: Path,
    folder: Path,
    started: Callable[[subprocess.Popen], None] | None,
) -> subprocess.CompletedProcess:
    if not program:
        raise LabCatalogError(NO_PYTHON)
    try:
        # -I keeps the user's own settings out; -X utf8 keeps printed text readable on Windows.
        return run_process([program, "-I", "-X", "utf8", path.name], folder, started)
    except OSError:
        raise LabCatalogError(
            f"Python not found at {program}; check the path on the Settings page"
        ) from None


def python_status(program: str) -> PythonStatus:
    check = PYTHON_CHECK.format(packages=repr(PYTHON_PACKAGES))
    try:
        done = run_process([program, "-I", "-c", check])
    except OSError:
        raise LabCatalogError(f"No Python at {program}") from None
    if done.returncode != 0:
        raise LabCatalogError(f"Python stopped with an error: {done.stderr.strip()[-500:]}")
    version, *missing = done.stdout.split()
    return PythonStatus(version, missing)


def written(folder: Path, given: set[str]) -> dict[str, bytes]:
    return {
        p.name: p.read_bytes()
        for p in sorted(folder.iterdir())
        if p.is_file() and p.name not in given
    }
