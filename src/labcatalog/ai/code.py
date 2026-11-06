import ast
import re
import tempfile
from pathlib import Path

from labcatalog.stats import rbridge

# A whole answer wrapped in one markdown code fence, as models often send code.
FENCED = re.compile(r"^\s*```[^\n]*\n(.*?)\n?```\s*$", re.DOTALL)
# Prints R's message, which starts file:line:column:, and nothing when the script parses.
R_PARSE = (
    "tryCatch(invisible(parse(file = commandArgs(TRUE)[1], encoding = 'UTF-8')), "
    "error = function(e) cat(conditionMessage(e)))"
)
R_PLACE = re.compile(r":(\d+):\d+: ([^\n]*)")


def unfenced(text: str) -> str:
    found = FENCED.match(text)
    return found.group(1) if found else text


def syntax_error(script: str, language: str, rscript: str | None) -> str:
    # Empty when the script parses, or when no Rscript is set to parse an R one.
    if language == "python":
        try:
            ast.parse(script)
        except SyntaxError as err:
            return placed(script, err.lineno or 0, err.msg)
        return ""
    if not rscript:
        return ""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "draft.R"
        path.write_text(script, encoding="utf-8")
        message = rbridge.run_now(rscript, ["-e", R_PARSE, str(path)])
    found = R_PLACE.search(message)
    return placed(script, int(found.group(1)), found.group(2)) if found else message.strip()


def placed(script: str, line: int, message: str) -> str:
    lines = script.splitlines()
    text = lines[line - 1].strip() if 0 < line <= len(lines) else ""
    return f"Line {line}: {message}" + (f' (in "{text}")' if text else "")
