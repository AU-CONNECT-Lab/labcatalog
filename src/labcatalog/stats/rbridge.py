import json
import subprocess
from dataclasses import dataclass

from labcatalog.exceptions import RError
from labcatalog.processes import NEW_GROUP, end_tree

CFA_PACKAGES = ("lavaan", "semTools")
ANALYSIS_PACKAGES = ("psych", "effectsize", "MBESS")
MULTILEVEL_PACKAGES = ("lme4", "lmerTest", "performance")
MEDIATION_PACKAGES = ("modsem",)
IMPUTATION_PACKAGES = ("mice", "miceadds")
ALL_PACKAGES = (
    CFA_PACKAGES
    + ANALYSIS_PACKAGES
    + MULTILEVEL_PACKAGES
    + MEDIATION_PACKAGES
    + IMPUTATION_PACKAGES
)
MISSING_PACKAGES = 3
# The R processes running now, so that closing the window can end them.
RUNNING: set[subprocess.Popen] = set()
CHECK = """\
missing <- Filter(function(p) !requireNamespace(p, quietly = TRUE), c({packages}))
if (length(missing) > 0) {{
  cat(missing, sep = "\\n")
  quit(status = 3)
}}
"""


@dataclass
class RStatus:
    version: str
    missing: list[str]


def install_command(packages: list[str] | tuple[str, ...]) -> str:
    return f"install.packages(c({', '.join(json.dumps(p) for p in packages)}))"


def package_check(packages: tuple[str, ...]) -> str:
    # Stops R with status 3 and the missing names, which run_r turns into install advice.
    return CHECK.format(packages=", ".join(json.dumps(p) for p in packages))


def r_status(rscript: str, packages: tuple[str, ...] = ALL_PACKAGES) -> RStatus:
    names = ", ".join(json.dumps(p) for p in packages)
    check = (
        "cat(R.version.string, '\\n'); "
        f"for (p in c({names})) if (!requireNamespace(p, quietly = TRUE)) cat(p, '\\n')"
    )
    lines = run_r(rscript, ["-e", check]).split("\n")
    return RStatus(version=lines[0].strip(), missing=[s.strip() for s in lines[1:] if s.strip()])


def run_r(rscript: str, args: list[str]) -> str:
    try:
        process = subprocess.Popen(
            [rscript, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **NEW_GROUP,
        )
    except OSError:
        raise RError(
            f"Rscript not found at {rscript}; check the path on the Settings page"
        ) from None
    RUNNING.add(process)
    try:
        stdout, stderr = process.communicate()
    finally:
        RUNNING.discard(process)
    if process.returncode == MISSING_PACKAGES:
        missing = stdout.split()
        raise RError(
            f"R is missing {', '.join(missing)}; install them in R with: {install_command(missing)}"
        )
    if process.returncode != 0:
        raise RError(f"R stopped with an error: {stderr.strip()[-500:]}")
    return stdout


def stop_all() -> None:
    # Ends every R still running, with the workers it started, as the window closes.
    for process in list(RUNNING):
        end_tree(process)
