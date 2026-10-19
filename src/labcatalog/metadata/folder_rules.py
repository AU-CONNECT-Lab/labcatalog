import re
from collections import Counter
from dataclasses import dataclass, field

from labcatalog.exceptions import EditError
from labcatalog.sources.folder_source import ID, file_pattern

# A key-value part of a path, such as sub-01 or ses-1 in BIDS.
FIELD = re.compile(r"([A-Za-z]+)-([A-Za-z0-9]+)")
# Not a field: the part of each name that matches the study's ID pattern.
BY_PATTERN = ""
# Fields that vary, such as run-*, which some names have and others leave out.
OPTIONAL = re.compile(r"(_[A-Za-z]+-\*)+(?=[_.])")
SHOWN = 5
# Only the most common kinds of file are counted, as each count reads every path.
COUNTED = 20


@dataclass
class Field:
    key: str
    values: int


@dataclass
class Rule:
    files: str
    people: int
    count: int


@dataclass
class FolderCount:
    people: int
    files: int
    unmatched: list[str]
    # IDs with more than one file, with how many each has.
    repeated: dict[str, int] = field(default_factory=dict)
    not_in_roster: list[str] = field(default_factory=list)
    roster_without_files: int = 0
    off_pattern: list[str] = field(default_factory=list)


def tokens(part: str, last: bool) -> tuple[list[str], str]:
    # A file name's extension stays out of its tokens.
    stem, dot, extension = part.partition(".") if last else (part, "", "")
    return stem.split("_"), dot + extension


def path_fields(paths: list[str]) -> list[Field]:
    values: dict[str, set[str]] = {}
    for path in paths:
        parts = path.split("/")
        for i, part in enumerate(parts):
            for token in tokens(part, i == len(parts) - 1)[0]:
                if found := FIELD.fullmatch(token):
                    values.setdefault(found[1], set()).add(found[2])
    return sorted(
        (Field(key, len(found)) for key, found in values.items()), key=lambda f: -f.values
    )


def id_field(fields: list[Field], pattern: str | None) -> str | None:
    keys = [f.key for f in fields]
    if "sub" in keys:
        return "sub"
    if keys:
        return keys[0]
    return BY_PATTERN if pattern else None


def same_wave(value: str, wave: str) -> bool:
    return value == wave or (value.isdigit() and wave.isdigit() and int(value) == int(wave))


def wave_key(paths: list[str], key: str, wave: str) -> str | None:
    # A session is a folder of its own, as ses-1/ is in BIDS; run-1 in a file name is not.
    folders: dict[str, set[str]] = {}
    for path in paths:
        for part in path.split("/")[:-1]:
            if found := FIELD.fullmatch(part):
                folders.setdefault(found[1], set()).add(found[2])
    for name in sorted(folders, key=lambda k: k != "ses"):
        values = folders[name]
        if name != key and len(values) > 1 and any(same_wave(v, wave) for v in values):
            return name
    return None


def template(path: str, key: str, pattern: re.Pattern[str] | None, varying: set[str]) -> str | None:
    parts = path.split("/")
    out, placed = [], False
    for i, part in enumerate(parts):
        words, extension = tokens(part, i == len(parts) - 1)
        kept = []
        for word in words:
            found = FIELD.fullmatch(word)
            if key == BY_PATTERN and pattern is not None and pattern.fullmatch(word):
                kept.append("*" if placed else ID)
                placed = True
            elif found and found[1] == key:
                kept.append(f"{key}-*" if placed else f"{key}-{ID}")
                placed = True
            elif found and found[1] in varying:
                kept.append(f"{found[1]}-*")
            else:
                kept.append(word)
        out.append("_".join(kept) + extension)
    return "/".join(out) if placed else None


def suggest(paths: list[str], key: str, wave: str, pattern: str | None = None) -> list[Rule]:
    # Rules that count each kind of file once per person, the most people first.
    compiled = re.compile(pattern) if key == BY_PATTERN and pattern else None
    by_wave = wave_key(paths, key, wave)
    varying = {f.key for f in path_fields(paths) if f.values > 1} - {key, by_wave}
    kept = [
        p
        for p in paths
        if by_wave is None
        or not any(m[1] == by_wave and not same_wave(m[2], wave) for m in FIELD.finditer(p))
    ]
    made = Counter(t for p in kept if (t := template(p, key, compiled, varying)))
    # The same rule with its optional fields as *, so names with and without them both count.
    made.update({OPTIONAL.sub("*", t): n for t, n in made.items() if OPTIONAL.search(t)})
    # Of rules that count the same files, the one with the fewest wildcards.
    ordered = sorted(made.most_common(COUNTED), key=lambda pair: pair[0].count("*"))
    rules, counted = [], set()
    for files, _ in ordered:
        seen = count_folder(paths, files)
        matched = frozenset(paths) - frozenset(seen.unmatched)
        if matched not in counted:
            counted.add(matched)
            rules.append(Rule(files, seen.people, seen.files))
    rules.sort(key=lambda r: (-r.people, -r.count, r.files.count("*"), r.files))
    return rules[:SHOWN]


def count_folder(
    paths: list[str],
    files: str,
    roster: set[str] | None = None,
    pattern: str | None = None,
) -> FolderCount:
    if files.count(ID) != 1:
        raise EditError("Files: put {id} once, where each file's path holds the ID")
    matcher = file_pattern(files)
    per_person: Counter[str] = Counter()
    unmatched = []
    for path in paths:
        found = matcher.fullmatch(path)
        if found:
            per_person[found.group("id")] += 1
        else:
            unmatched.append(path)
    people = sorted(per_person)
    compiled = re.compile(pattern) if pattern else None
    return FolderCount(
        people=len(people),
        files=sum(per_person.values()),
        unmatched=unmatched,
        repeated={i: n for i, n in per_person.items() if n > 1},
        not_in_roster=[i for i in people if roster is not None and i not in roster],
        roster_without_files=len(roster - set(people)) if roster is not None else 0,
        off_pattern=[i for i in people if compiled and not compiled.fullmatch(i)],
    )
