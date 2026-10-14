from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from labcatalog import defaults
from labcatalog.config import ProjectConfig
from labcatalog.exceptions import MetadataError, ProjectNotFoundError
from labcatalog.issues import Issue, issues_from_validation_error
from labcatalog.schema import Instrument, StudyContent

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass
class Project:
    root: Path
    config: ProjectConfig
    instruments: dict[str, Instrument]
    studies: dict[str, StudyContent]


def load_project(root: Path) -> Project:
    root = root.resolve()
    config_path = root / defaults.CONFIG_FILENAME
    if not config_path.is_file():
        raise ProjectNotFoundError(f"No {defaults.CONFIG_FILENAME} found in {root}")

    issues: list[Issue] = []
    config = load_model(config_path, ProjectConfig, root, issues)
    instruments = load_models(root / defaults.INSTRUMENTS_DIR, Instrument, "id", root, issues)
    studies = load_models(root / defaults.STUDIES_DIR, StudyContent, "study", root, issues)
    if issues:
        raise MetadataError(issues)
    return Project(root=root, config=config, instruments=instruments, studies=studies)


def load_yaml(path: Path) -> Any:
    # Bytes let PyYAML detect the encoding and report undecodable files as YAML errors.
    return yaml.safe_load(path.read_bytes())


def load_model(path: Path, model: type[ModelT], root: Path, issues: list[Issue]) -> ModelT | None:
    location = path.relative_to(root).as_posix()
    try:
        data = load_yaml(path)
    except yaml.YAMLError as err:
        issues.append(yaml_issue(err, location))
        return None
    try:
        return model.model_validate(data if data is not None else {})
    except ValidationError as err:
        issues.extend(issues_from_validation_error(err, location))
        return None


def load_models(
    directory: Path, model: type[ModelT], key: str, root: Path, issues: list[Issue]
) -> dict[str, ModelT]:
    loaded: dict[str, ModelT] = {}
    seen_in: dict[str, str] = {}
    for path in sorted(p for p in directory.glob("*") if p.suffix in defaults.YAML_SUFFIXES):
        item = load_model(path, model, root, issues)
        if item is None:
            continue
        name = getattr(item, key)
        location = path.relative_to(root).as_posix()
        if name in seen_in:
            issues.append(
                Issue(
                    level="error",
                    code="duplicate_id",
                    message=f"{key} '{name}' is also used in {seen_in[name]}",
                    location=location,
                )
            )
            continue
        loaded[name] = item
        seen_in[name] = location
    return loaded


def yaml_issue(err: yaml.YAMLError, location: str) -> Issue:
    mark = getattr(err, "problem_mark", None)
    if mark is not None:
        location = f"{location}:{mark.line + 1}"
    problem = getattr(err, "problem", None) or str(err)
    return Issue(
        level="error", code="yaml_syntax", message=f"Invalid YAML: {problem}", location=location
    )


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
