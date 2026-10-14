EXIT_OK = 0
EXIT_ISSUES = 1
# Exit code 2 is left to Click for command-line usage errors.


class LabCatalogError(Exception):
    exit_code = 9


class ProjectNotFoundError(LabCatalogError):
    exit_code = 3


class ConfigError(LabCatalogError):
    exit_code = 3


class MetadataError(LabCatalogError):
    exit_code = 3


class DataSourceError(LabCatalogError):
    exit_code = 4


class BuildError(LabCatalogError):
    exit_code = 5
