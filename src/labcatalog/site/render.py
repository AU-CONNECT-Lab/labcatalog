from pathlib import Path
from typing import Any

from labcatalog.check import CheckReport
from labcatalog.manifest import Manifest
from labcatalog.project import Project
from labcatalog.resolve import Catalog
from labcatalog.schema import Reference
from labcatalog.stats import Summary


def render_page(template_name: str, context: dict[str, Any]) -> str:
    raise NotImplementedError


def reference_href(reference: Reference, project: Project, out_dir: Path) -> str | None:
    raise NotImplementedError


def build_site(
    project: Project,
    catalog: Catalog,
    summary: Summary,
    report: CheckReport,
    snippets: dict[str, dict[str, str]],
    manifest: Manifest,
    out_dir: Path,
) -> Path:
    raise NotImplementedError
