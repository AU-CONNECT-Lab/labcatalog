from pathlib import Path

import bibtexparser
from bibtexparser.middlewares import LatexDecodingMiddleware
from bibtexparser.middlewares.names import (
    parse_single_name_into_parts,
    split_multiple_persons_names,
)
from bibtexparser.model import Block, DuplicateBlockKeyBlock

from labcatalog.issues import Issue
from labcatalog.paths import portable_path

Bibliography = dict[str, dict[str, str]]


def load_bibliography(path: Path, root: Path, issues: list[Issue]) -> Bibliography:
    if not path.is_file():
        return {}
    location = portable_path(path, root).as_posix()
    # No parse stack: @string macros and # joins are evaluated below, the way BibTeX does.
    library = bibtexparser.parse_string(path.read_text(encoding="utf-8-sig"), parse_stack=[])
    issues.extend(block_issue(block, location) for block in library.failed_blocks)
    strings = {s.key.lower(): s.value for s in library.strings}
    for entry in library.entries:
        for field in entry.fields:
            field.value = evaluate(field.value, strings)
    # Braces stay so that "{World Health Organization}" is still one name when names are split.
    library = LatexDecodingMiddleware(keep_braced_groups=True).transform(library)
    return {e.key: {f.key.lower(): f.value for f in e.fields} for e in library.entries}


def block_issue(block: Block, location: str) -> Issue:
    where = f"{location}:{(block.start_line or 0) + 1}"
    if isinstance(block, DuplicateBlockKeyBlock):
        message = f"key '{block.key}' is used more than once"
        return Issue(level="error", code="duplicate_id", message=message, location=where)
    message = "Invalid BibTeX: could not read this entry" + (
        f" ({block.error})" if str(block.error) else ""
    )
    return Issue(level="error", code="bib_syntax", message=message, location=where)


def evaluate(raw: object, strings: dict[str, str], depth: int = 0) -> str:
    if not isinstance(raw, str):
        return "" if raw is None else str(raw)
    out = []
    for part in split_concatenation(raw):
        if len(part) >= 2 and (part[0], part[-1]) in (("{", "}"), ('"', '"')):
            out.append(part[1:-1])
        elif part.lower() in strings and depth < 10:
            out.append(evaluate(strings[part.lower()], strings, depth + 1))
        else:
            out.append(part)
    return "".join(out)


def split_concatenation(raw: str) -> list[str]:
    parts, current, depth, quoted = [], [], 0, False
    for ch in raw:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif ch == '"' and depth == 0:
            quoted = not quoted
        elif ch == "#" and depth == 0 and not quoted:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def citation(bibliography: Bibliography, key: str) -> str:
    entry = bibliography.get(key)
    if entry is None:
        return key
    year = entry.get("year") or entry.get("date", "")[:4]
    venue = next(
        (entry[f] for f in ("journal", "journaltitle", "booktitle", "publisher") if entry.get(f)),
        "",
    )
    head = " ".join(
        p for p in (short_authors(entry.get("author", "")), f"({year})" if year else "") if p
    )
    return " ".join(sentence(unbrace(p)) for p in (head, entry.get("title", ""), venue) if p)


def short_authors(field: str) -> str:
    names = [last_name(name) for name in split_multiple_persons_names(field)] if field else []
    return f"{names[0]} et al." if len(names) > 2 else " & ".join(names)


def last_name(name: str) -> str:
    parts = parse_single_name_into_parts(name)
    return unbrace(" ".join(parts.von + parts.last))


def sentence(text: str) -> str:
    return text if text.endswith((".", "?", "!")) else f"{text}."


def unbrace(text: str) -> str:
    return text.replace("{", "").replace("}", "")
