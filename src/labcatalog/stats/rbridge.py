import json
import subprocess
from dataclasses import dataclass

from labcatalog.exceptions import RError

CFA_PACKAGES = ("lavaan", "semTools")
ANALYSIS_PACKAGES = ("psych", "effectsize", "MBESS")
MULTILEVEL_PACKAGES = ("lme4", "lmerTest", "performance")
MEDIATION_PACKAGES = ("modsem",)
ALL_PACKAGES = CFA_PACKAGES + ANALYSIS_PACKAGES + MULTILEVEL_PACKAGES + MEDIATION_PACKAGES
MISSING_PACKAGES = 3
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
        done = subprocess.run(
            [rscript, *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except OSError:
        raise RError(
            f"Rscript not found at {rscript}; check the path on the Settings page"
        ) from None
    if done.returncode == MISSING_PACKAGES:
        missing = done.stdout.split()
        raise RError(
            f"R is missing {', '.join(missing)}; install them in R with: {install_command(missing)}"
        )
    if done.returncode != 0:
        raise RError(f"R stopped with an error: {done.stderr.strip()[-500:]}")
    return done.stdout
