from dataclasses import dataclass
from pathlib import Path
from typing import Any

from labcatalog.config import ProjectConfig
from labcatalog.issues import Issue
from labcatalog.schema import Instrument, StudyContent


@dataclass
class Project:
    root: Path
    config: ProjectConfig
    instruments: dict[str, Instrument]
    studies: dict[str, StudyContent]


def find_project_root(start: Path) -> Path:
    raise NotImplementedError


def load_yaml(path: Path) -> dict[str, Any]:
    raise NotImplementedError


def load_instruments(directory: Path) -> dict[str, Instrument]:
    raise NotImplementedError


def load_studies(directory: Path) -> dict[str, StudyContent]:
    raise NotImplementedError


def load_project(root: Path) -> Project:
    raise NotImplementedError


def validate_project(project: Project) -> list[Issue]:
    raise NotImplementedError


def check_vocab(project: Project) -> list[Issue]:
    raise NotImplementedError


def check_cross_references(project: Project) -> list[Issue]:
    raise NotImplementedError


def check_custom_fields(project: Project) -> list[Issue]:
    raise NotImplementedError


def check_missing_code_collisions(project: Project) -> list[Issue]:
    raise NotImplementedError


def init_project(target: Path, example: bool = True) -> Path:
    raise NotImplementedError
