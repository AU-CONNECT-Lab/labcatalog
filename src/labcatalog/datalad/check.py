import shutil

from labcatalog.data.manifest import used_paths
from labcatalog.datalad.annex import group_by_dataset
from labcatalog.issues import Issue
from labcatalog.project import Project


def check_git_annex(project: Project) -> list[Issue]:
    if shutil.which("git-annex") or not group_by_dataset(used_paths(project.config, project.root)):
        return []
    message = (
        "The project's files are in DataLad datasets, but git-annex is not on PATH, so the "
        "manifest leaves out their versions and History cannot show uncommitted changes; "
        "set the path to datalad on the Settings page or put git-annex on PATH"
    )
    return [Issue(level="warning", code="git_annex_not_found", message=message)]
