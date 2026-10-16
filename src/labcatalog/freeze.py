import re
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

from labcatalog import defaults
from labcatalog.annex import group_by_dataset
from labcatalog.dataladbridge import run_datalad
from labcatalog.exceptions import DataladError, FreezeError
from labcatalog.manifest import Manifest, build_manifest, original_branch, run_git, used_paths
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
    groups = group_by_dataset(used_paths(project, datasets))
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
