from collections import Counter
from dataclasses import dataclass
from itertools import combinations

import pandas as pd

from labcatalog.sources import LoadedDataset, has_id

# A person and a group may be written alike, so each key says which it is.
PERSON, GROUP = "id:", "group:"


@dataclass
class Links:
    # Each file's row for every unit: a group, or each person of a group that a file holds several of.
    rows: dict[str, pd.Series]
    # Person key -> group key, for the groups taken person by person.
    split: dict[str, str]
    # Rows left out because their ID repeats within a file.
    repeated: int
    # Groups where two files each hold several people and none in common.
    crossed: int
    # The IDs and groups of the rows left out as repeated, by file.
    repeated_keys: dict[str, set[str]]


def link(datasets: dict[str, LoadedDataset], names: list[str], correlate_by: str) -> Links:
    by_group = correlate_by not in ("id", "none")
    # IDs belong to their study, so files of several studies share no one.
    several = len({datasets[name].config.study for name in names}) > 1
    parts, repeated, repeated_keys = [], 0, {}
    for name in names:
        loaded = datasets[name]
        ids = loaded.frame[loaded.id_column].astype("string")
        ids = PERSON + study_keys(loaded, ids.where(has_id(ids)), several)
        # Someone the roster gives no group links by their own ID, as in a file without groups.
        groups = (
            (GROUP + study_keys(loaded, loaded.group.astype("string"), several)).fillna(ids)
            if by_group and loaded.group is not None
            else ids
        )
        rows = pd.DataFrame(
            {"name": name, "id": ids.to_numpy(), "group": groups.to_numpy(), "row": range(len(ids))}
        )
        twice = (rows["id"].notna() & rows["id"].duplicated(keep=False)).to_numpy()
        repeated += int(twice.sum())
        repeated_keys[name] = {*rows["id"][twice].dropna(), *rows["group"][twice].dropna()}
        parts.append(rows[~twice & rows["group"].notna().to_numpy()])
    found: dict[str, dict[str, int]] = {name: {} for name in names}
    split: dict[str, str] = {}
    crossed = 0
    every = pd.concat(parts) if parts else pd.DataFrame(columns=["name", "id", "group", "row"])
    # Plain lists, since a pandas frame per group is slow when there are thousands of groups.
    cells: dict[str, list[tuple[str, object, int]]] = {}
    columns = (every[c].tolist() for c in ("group", "name", "id", "row"))
    for group, name, person, row in zip(*columns, strict=True):
        cells.setdefault(group, []).append((name, person, row))
    for group, cell in cells.items():
        counts = Counter(name for name, _, _ in cell)
        if max(counts.values()) == 1:
            for name, _, row in cell:
                found[name][group] = int(row)
            continue
        several = [
            {p for n, p, _ in cell if n == name and not pd.isna(p)}
            for name, k in counts.items()
            if k > 1
        ]
        people = set().union(*several)
        crossed += any(a.isdisjoint(b) for a, b in combinations(several, 2))
        for name in counts:
            ids = [p for n, p, _ in cell if n == name]
            rows = [r for n, _, r in cell if n == name]
            for person in people:
                if person in ids:
                    found[name][person] = int(rows[ids.index(person)])
                # A file with one row for the group, not one of its people, gives it to each person.
                elif len(ids) == 1 and ids[0] not in people:
                    found[name][person] = int(rows[0])
        split |= dict.fromkeys(people, group)
    rows = {name: pd.Series(found[name], dtype=int) for name in names}
    return Links(rows, split, repeated, crossed, repeated_keys)


def study_keys(loaded: LoadedDataset, keys: pd.Series, several: bool) -> pd.Series:
    return f"{loaded.config.study}/" + keys if several else keys


def as_written(key: str) -> str:
    return key.partition(":")[2]
