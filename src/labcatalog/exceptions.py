from datetime import datetime
from pathlib import Path

from labcatalog.issues import Issue

EXIT_OK = 0
EXIT_ISSUES = 1
# Exit code 2 is left to Click for command-line usage errors.
EXIT_UNEXPECTED = 9


class LabCatalogError(Exception):
    exit_code = EXIT_UNEXPECTED


class ProjectNotFoundError(LabCatalogError):
    exit_code = 3


class ProjectExistsError(LabCatalogError):
    exit_code = 3


class MetadataError(LabCatalogError):
    exit_code = EXIT_ISSUES

    def __init__(self, issues: list[Issue]) -> None:
        super().__init__(f"{len(issues)} problem(s) in the project files")
        self.issues = issues


class DataSourceError(LabCatalogError):
    exit_code = 4


class CodebookError(LabCatalogError):
    exit_code = EXIT_ISSUES


class ExportError(LabCatalogError):
    exit_code = EXIT_ISSUES


class FreezeError(LabCatalogError):
    exit_code = EXIT_ISSUES


class EditError(LabCatalogError):
    exit_code = EXIT_ISSUES


class PrepareBusyError(LabCatalogError):
    exit_code = EXIT_ISSUES

    def __init__(self, by: str, since: datetime, path: Path) -> None:
        super().__init__(
            f"{by} has been running the prepare steps since {since:%Y-%m-%d %H:%M}; "
            f"if that run has ended, delete {path}"
        )
        self.by, self.since = by, since


class RError(LabCatalogError):
    pass


class MplusError(LabCatalogError):
    pass


class DataladError(LabCatalogError):
    exit_code = EXIT_ISSUES


class LLMError(LabCatalogError):
    pass
