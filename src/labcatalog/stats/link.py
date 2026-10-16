from dataclasses import dataclass
from itertools import combinations

import pandas as pd

from labcatalog.sources import LoadedDataset


@dataclass
class Links:
    # Each file's row for every unit: a group, or each person of a group that a file holds several of.
    rows: dict[str, pd.Series]
    # Person -> group, for the groups taken person by person.
    split: dict[str, str]
    # Rows left out because their ID repeats within a file.
    repeated: int
    # Groups where two files each hold several people and none in common.
    crossed: int


def link(datasets: dict[str, LoadedDataset], names: list[str], correlate_by: str) -> Links:
    by_group = correlate_by not in ("id", "none")
    parts, repeated = [], 0
    for name in names:
        loaded = datasets[name]
        ids = loaded.frame[loaded.id_column].astype("string")
        groups = loaded.group.astype("string") if by_group and loaded.group is not None else ids
        rows = pd.DataFrame(
            {"name": name, "id": ids.to_numpy(), "group": groups.to_numpy(), "row": range(len(ids))}
        )
        twice = (rows["id"].notna() & rows["id"].duplicated(keep=False)).to_numpy()
        repeated += int(twice.sum())
        parts.append(rows[~twice & rows["group"].notna().to_numpy()])
    found: dict[str, dict[str, int]] = {name: {} for name in names}
    split: dict[str, str] = {}
    crossed = 0
    every = pd.concat(parts) if parts else pd.DataFrame(columns=["name", "id", "group", "row"])
    for group, cell in every.groupby("group", sort=False):
        counts = cell["name"].value_counts()
        if counts.max() == 1:
            for name, row in zip(cell["name"], cell["row"], strict=True):
                found[name][group] = int(row)
            continue
        several = [
            set(cell.loc[cell["name"] == n, "id"].dropna()) for n in counts.index[counts > 1]
        ]
        people = set().union(*several)
        crossed += any(a.isdisjoint(b) for a, b in combinations(several, 2))
        for name, own in cell.groupby("name", sort=False):
            ids, rows = own["id"].tolist(), own["row"].tolist()
            for person in people:
                if person in ids:
                    found[name][person] = int(rows[ids.index(person)])
                # A file with one row for the group, not one of its people, gives it to each person.
                elif len(ids) == 1 and ids[0] not in people:
                    found[name][person] = int(rows[0])
        split |= dict.fromkeys(people, group)
    rows = {name: pd.Series(found[name], dtype=int) for name in names}
    return Links(rows, split, repeated, crossed)
