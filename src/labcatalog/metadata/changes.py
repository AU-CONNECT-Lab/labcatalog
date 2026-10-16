import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from labcatalog import defaults
from labcatalog.exceptions import EditError, MetadataError
from labcatalog.issues import Issue
from labcatalog.metadata import editing
from labcatalog.metadata.validate import validate_project
from labcatalog.project import Project, load_project, references_root


@dataclass
class Change:
    path: str
    text: str
    opened: editing.Opened | None = None
    # Set to delete the file, as when a study file is renamed.
    removed: bool = False


def check(project: Project, found: list[Change]) -> list[Issue]:
    issues = [
        issue
        for change in found
        if not change.removed
        for issue in editing.check_text(change.path, change.text)
    ]
    return issues or new_issues(project, found)


def new_issues(project: Project, found: list[Change]) -> list[Issue]:
    # Checks across files, on copies of the settings without the data, so only new problems count.
    before = {same(i) for i in copy_issues(project, [])}
    after = copy_issues(project, found)
    return [i for i in after if i.level == "error" and same(i) not in before]


def same(issue: Issue) -> tuple[str, str]:
    # An inserted dataset shifts the numbers of the entries after it.
    return issue.code, re.sub(r"\[\d+\]", "[]", issue.message)


def copy_issues(project: Project, found: list[Change]) -> list[Issue]:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        shutil.copyfile(project.root / defaults.CONFIG_FILENAME, root / defaults.CONFIG_FILENAME)
        for folder in (defaults.INSTRUMENTS_DIR, defaults.STUDIES_DIR, defaults.MAPS_DIR):
            if (project.root / folder).is_dir():
                shutil.copytree(project.root / folder, root / folder)
        bib = references_root(project.config, project.root) / defaults.BIB_FILENAME
        if bib.is_file():
            target = references_root(project.config, root) / defaults.BIB_FILENAME
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(bib, target)
        for change in found:
            path = root / change.path
            if change.removed:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.text, encoding="utf-8")
        try:
            issues = validate_project(load_project(root))
        except MetadataError as err:
            issues = err.issues
        # Each copy has its own folder, which some messages name.
        return [i.model_copy(update={"message": i.message.replace(str(root), "")}) for i in issues]


def write(project: Project, found: list[Change]) -> None:
    # Every file is checked first, so a refused save leaves all of them as they were.
    for change in found:
        if change.opened is not None:
            path = project.root / change.opened.path
            if path.stat().st_mtime_ns != change.opened.modified:
                raise EditError(f"{change.path} changed on disk meanwhile; start again")
        elif (project.root / change.path).exists():
            raise EditError(f"{change.path} already exists")
    for change in found:
        if change.removed:
            (project.root / change.path).unlink()
        elif change.opened is not None:
            editing.save_file(project.root, change.opened, change.text)
        else:
            path = project.root / change.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change.text, encoding="utf-8", newline="\n")
