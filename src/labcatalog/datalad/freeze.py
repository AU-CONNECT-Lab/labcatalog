import os
import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.data.manifest import Manifest, build_manifest, used_paths
from labcatalog.datalad.annex import group_by_dataset
from labcatalog.datalad.bridge import run_datalad
from labcatalog.datalad.versions import ADJUSTED, original_branch, run_git
from labcatalog.exceptions import DataladError, FreezeError
from labcatalog.project import Project
from labcatalog.sources import LoadedDataset

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
RECORD_ONLY = (
    "The data are not in DataLad, so a freeze only writes a record: it shows later whether "
    "the data changed, but data that are overwritten cannot be got back."
)


class Freeze(BaseModel):
    name: str
    frozen_at: datetime
    # The git tag on each DataLad dataset the data come from; None when none are in DataLad.
    tag: str | None = None
    participants: dict[str, int]
    manifest: Manifest


def freeze_project(
    project: Project,
    datasets: dict[str, LoadedDataset],
    participants: dict[str, int],
    name: str,
    datalad: str | None,
) -> tuple[Path, Freeze]:
    folder = project.root / defaults.FREEZES_DIR
    check_name(folder, name)
    groups = datalad_datasets(project)
    if groups and not datalad:
        raise DataladError(
            "The data are in DataLad datasets, which a freeze saves and tags; "
            "set the path to datalad on the Settings page"
        )
    for root in groups:
        if run_git(root, "tag", "--list", name):
            raise FreezeError(f"{root} already has a tag named {name}")

    # Deepest first, so a superdataset records the new state of its subdatasets.
    for root in sorted(groups, key=lambda r: len(r.parts), reverse=True):
        inside = [c.relative_to(root).as_posix() for c in groups if root in c.parents]
        run_datalad(datalad, ["save", "-m", f"Freeze {name}", *groups[root], *inside], cwd=root)

    record = Freeze(
        name=name,
        frozen_at=datetime.now().replace(microsecond=0),
        tag=name if groups else None,
        participants=participants,
        manifest=build_manifest(project, datasets),
    )
    folder.mkdir(exist_ok=True)
    path = folder / f"{date.today()}_{name}.json"
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    if groups:
        holding = group_by_dataset([path])
        for root, paths in holding.items():
            run_datalad(datalad, ["save", "-m", f"Freeze {name}: record", *paths], cwd=root)
        # The original branch, because datalad save --version-tag tags a commit no clone has.
        for root in {*groups, *holding}:
            run_git(root, "tag", "-a", name, "-m", f"Freeze {name}", original_branch(root))
    return path, record


def datalad_datasets(project: Project) -> dict[Path, list[str]]:
    return group_by_dataset(used_paths(project.config, project.root))


def check_name(folder: Path, name: str) -> None:
    if not NAME.fullmatch(name):
        raise FreezeError(
            f"'{name}' cannot name a freeze; use letters, digits, '.', '-' and '_', "
            "for example 2026-06-submission"
        )
    if any(folder.glob(f"*_{name}.json")):
        raise FreezeError(f"There is already a freeze named {name} in {defaults.FREEZES_DIR}")


def list_freezes(root: Path) -> list[Freeze]:
    found = [
        Freeze.model_validate_json(path.read_text(encoding="utf-8"))
        for path in (root / defaults.FREEZES_DIR).glob("*.json")
    ]
    return sorted(found, key=lambda f: f.frozen_at, reverse=True)


def open_freeze(project_root: Path, record: Freeze, folder: Path, datalad: str) -> Path:
    if record.tag is None:
        raise FreezeError(f"{record.name} is only a record; {RECORD_ONLY}")
    roots = [(project_root / r.path).resolve() for r in record.manifest.datalad]
    tops = [r for r in roots if not any(other in r.parents for other in roots)]
    if not any(t == project_root or t in project_root.parents for t in tops):
        raise FreezeError(f"{record.name} cannot be opened: the project folder was not in DataLad")
    # The copy keeps the datasets where they were relative to each other and to the project.
    base = Path(os.path.commonpath(tops))
    for top in tops:
        copy = folder / top.relative_to(base)
        run_datalad(datalad, ["clone", str(top), str(copy)])
        checkout_tag(copy, record.tag)
    # Installed at the commit their superdataset recorded, which is the tagged one.
    for root in sorted(set(roots) - set(tops), key=lambda r: len(r.parts)):
        top = next(t for t in tops if t in root.parents)
        inside = root.relative_to(top).as_posix()
        run_datalad(datalad, ["get", "-n", inside], cwd=folder / top.relative_to(base))
    return folder / project_root.relative_to(base)


def checkout_tag(root: Path, tag: str) -> None:
    adjusted = run_git(root, "branch", "--show-current").startswith(ADJUSTED)
    run_git(root, "checkout", "-q", "-b", f"freeze-{tag}", tag)
    if adjusted:
        # Checked out as is, annexed files are link text; adjusting turns them into pointer files.
        run_git(root, "annex", "adjust", "--unlock")


def differences(record: Freeze, manifest: Manifest) -> list[str]:
    now = {f.dataset: f.sha256 for f in manifest.files}
    return [f.dataset for f in record.manifest.files if now.get(f.dataset) != f.sha256]
