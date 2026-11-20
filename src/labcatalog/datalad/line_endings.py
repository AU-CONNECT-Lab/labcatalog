import re
from collections.abc import Iterator
from pathlib import Path

from labcatalog.data.manifest import present
from labcatalog.datalad.annex import group_by_dataset
from labcatalog.datalad.bridge import run_datalad
from labcatalog.datalad.versions import git_output, run_git
from labcatalog.exceptions import DataladError
from labcatalog.paths import expand_path
from labcatalog.project import Project

ATTRIBUTES = ".gitattributes"
ATTRIBUTE = "-text"
MESSAGE = "Keep line endings as they are"
FORMAT = "--format=%(eolinfo:index)%x09%(eolattr)%x09%(path)"
TEXT = {"lf", "crlf", "mixed"}
# Windows takes a command line of 32,767 characters.
ARGUMENT_CHARACTERS = 20000


def git_names(root: Path, *args: str, given: str | None = None) -> list[str]:
    # Separated by NUL, so a name with spaces or accents comes as it is.
    found = git_output(root, "--literal-pathspecs", *args, given=given)
    return [name for name in found.split("\0") if name]


def annexed(root: Path, paths: list[str]) -> set[str]:
    # A dataset without an annex keeps every file in git.
    if not run_git(root, "config", "--default", "", "--get", "annex.uuid"):
        return set()
    return set(git_names(root, "annex", "find", "--include", "*", "--print0", *paths))


def git_text(root: Path, paths: list[str]) -> list[tuple[str, str]]:
    # The text attribute and name of each file git holds itself and takes for text.
    held = annexed(root, paths)
    rows = (row.split("\t", 2) for row in git_names(root, "ls-files", "-z", FORMAT, "--", *paths))
    return [(attribute, n) for content, attribute, n in rows if content in TEXT and n not in held]


def convertible(root: Path, paths: list[str]) -> list[str]:
    # git writes these out with the line endings of whichever computer checks them out.
    return [name for attribute, name in git_text(root, paths) if attribute != ATTRIBUTE]


def checksummed(project: Project) -> list[Path]:
    # What a manifest gives a checksum: the data and scores files, the rosters and step inputs.
    config, root = project.config, project.root
    sources = [p for d in config.datasets for p in (d.path, *d.scores.values()) if p]
    rosters = [study.roster.path for study in config.studies.values() if study.roster]
    inputs = [path for step in config.prepare for path in step.inputs]
    return present([expand_path(path, root) for path in (*sources, *rosters, *inputs)])


def convertible_files(project: Project) -> dict[Path, list[str]]:
    groups = group_by_dataset(checksummed(project))
    found = {root: convertible(root, paths) for root, paths in groups.items()}
    return {root: names for root, names in found.items() if names}


def rule(root: Path, name: str) -> str:
    # Only what a freeze checksums, so scripts elsewhere keep the line endings git gives them.
    pattern = "/" + re.sub(r"([*?\[\\])", r"\\\1", name) + ("/**" if (root / name).is_dir() else "")
    if re.search(r'[\s"]', pattern):
        pattern = '"' + pattern.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{pattern} {ATTRIBUTE}"


def add_rules(root: Path, paths: list[str], names: list[str]) -> list[str]:
    # Last in the file, where they outweigh a rule above them; gives the files that change in git.
    attributes = root / ATTRIBUTES
    written = attributes.read_bytes() if attributes.exists() else b""
    held = written.splitlines()
    new = [line for p in paths if (line := rule(root, p).encode()) not in held]
    if new:
        gap = b"" if not written or written.endswith(b"\n") else b"\n"
        attributes.write_bytes(written + gap + b"\n".join(new) + b"\n")
    # git took these in with LF whatever they hold here, and now is to take them as they are.
    chosen = ["--pathspec-from-file=-", "--pathspec-file-nul"]
    git_names(root, "add", "--renormalize", *chosen, given="\0".join(names))
    staged = git_names(root, "diff", "--cached", "--name-only", "-z")
    return list(dict.fromkeys([ATTRIBUTES, *staged]))


def unsaved(root: Path) -> list[str]:
    return git_names(root, "diff", "--name-only", "-z", "HEAD")


def batches(names: list[str]) -> Iterator[list[str]]:
    batch: list[str] = []
    for name in names:
        if batch and sum(len(n) + 3 for n in batch) + len(name) > ARGUMENT_CHARACTERS:
            yield batch
            batch = []
        batch.append(name)
    yield batch


def keep_line_endings(project: Project, datalad: str) -> list[Path]:
    found = convertible_files(project)
    # Saved with the message below, changes of the user's own would be lost among them.
    for root in sorted(found):
        if changed := unsaved(root):
            raise DataladError(
                f"{root} has changes not saved yet ({', '.join(changed[:3])}"
                f"{', ...' if len(changed) > 3 else ''}); save them in Data versions first"
            )
    groups = group_by_dataset(checksummed(project))
    for root in sorted(found):
        for names in batches(add_rules(root, groups[root], found[root])):
            run_datalad(datalad, ["save", "-m", MESSAGE, *names], cwd=root)
    return sorted(found)
