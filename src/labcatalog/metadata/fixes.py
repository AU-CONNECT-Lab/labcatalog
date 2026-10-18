import csv
import difflib
import io

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.config import dataset_by_name, map_name_of, missing_codes_for
from labcatalog.exceptions import EditError
from labcatalog.issues import Issue
from labcatalog.metadata import editing, records
from labcatalog.metadata.changes import Change
from labcatalog.project import Project
from labcatalog.sources import LoadedDataset

# Chosen for an unmapped item that was not asked in that dataset.
NOT_ASKED = "-"
EVIDENCE_ROWS = 50


def closest(word: str, choices: list[str]) -> str | None:
    found = difflib.get_close_matches(word, choices, n=1, cutoff=0.6)
    return found[0] if found else None


def map_rows(project: Project, dataset: str, rows: list[tuple[str, str, str]]) -> Change:
    # New rows go at the end of the dataset's column map; the rows already there stay as written.
    relative = map_file(project, dataset)
    opened = editing.open_file(project.root, relative)
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    text = opened.text.rstrip("\n") + "\n" + out.getvalue()
    return Change(relative, text, opened)


def map_line(project: Project, dataset: str, line: int, column: str | None) -> Change:
    # One row of the column map given another data column, or taken out when column is None.
    relative = map_file(project, dataset)
    opened = editing.open_file(project.root, relative)
    lines = opened.text.split("\n")
    if column is None:
        del lines[line - 1]
    else:
        row = next(csv.reader([lines[line - 1]]))
        row[next(csv.reader([lines[0]])).index("column")] = column
        out = io.StringIO()
        csv.writer(out, lineterminator="").writerow(row)
        lines[line - 1] = out.getvalue()
    return Change(relative, "\n".join(lines), opened)


def map_lines(project: Project, dataset: str) -> list[str]:
    return editing.open_file(project.root, map_file(project, dataset)).text.split("\n")


def map_file(project: Project, dataset: str) -> str:
    return f"{defaults.MAPS_DIR}/{map_name_of(project.config, dataset)}.csv"


def add_to_vocab(project: Project, kind: str, value: str) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    append_word(project, data, kind, value)
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def append_word(project: Project, data: CommentedMap, kind: str, value: str) -> None:
    if not data.get("vocab"):
        data["vocab"] = CommentedMap()
    vocab = data["vocab"]
    if kind not in vocab:
        # Written out in full, so the words that applied by default still apply.
        vocab[kind] = flow(getattr(project.config.vocab, kind))
    vocab[kind].append(value)


def replace_word(project: Project, places: list[dict], word: str) -> list[Change]:
    # Each place is one entry holding the word: a dataset in the settings or an administration.
    files: dict[str, tuple[editing.Opened, CommentedMap]] = {}

    def opened(relative: str) -> CommentedMap:
        if relative not in files:
            found = editing.open_file(project.root, relative)
            files[relative] = (found, records.load(found.text))
        return files[relative][1]

    for place in places:
        if "dataset" in place:
            data = opened(defaults.CONFIG_FILENAME)
            entry = next(d for d in data["datasets"] if d["name"] == place["dataset"])
        else:
            data = opened(project.study_files[place["study"]])
            entry = data["administrations"][place["administration"]]
        entry[place["field"]] = records.as_text(word)
    return [Change(path, records.dumped(data), found) for path, (found, data) in files.items()]


def not_asked(project: Project, dataset: str, instrument: str, items: list[str]) -> Change:
    # Recorded as dropped in that dataset, so the item stops counting as missing from the map.
    study = dataset_by_name(project.config, dataset).study
    relative = project.study_files.get(study)
    if relative is None:
        raise EditError(f"Study {study} has no file in {defaults.STUDIES_DIR}/")
    opened = editing.open_file(project.root, relative)
    data = records.load(opened.text)
    entry = next(
        a
        for a in data["administrations"]
        if a["instrument"] == instrument and dataset in a["datasets"]
    )
    if not entry.get("overrides"):
        entry["overrides"] = CommentedSeq()
    for item in items:
        override = CommentedMap()
        override.fa.set_flow_style()
        override.update(item=item, dataset=dataset, dropped=True)
        entry["overrides"].append(override)
    return Change(relative, records.dumped(data), opened)


def administered(project: Project, dataset: str) -> list[str]:
    return [
        a.instrument
        for content in project.studies.values()
        for a in content.administrations
        if dataset in a.datasets and a.instrument in project.instruments
    ]


def free_columns(project: Project, dataset: str, columns: list[str]) -> list[str]:
    # Data columns the map does not list yet, in the order of the data file.
    listed = {entry.column for entry in project.maps.get(map_name_of(project.config, dataset), [])}
    return [c for c in columns if c not in listed]


def flow(values: list[str]) -> CommentedSeq:
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq


def evidence(loaded: LoadedDataset, issue: Issue) -> list[dict[str, str]]:
    # The rows a data problem is about, as the person checking the source would look them up.
    column = issue.details.get("column")
    shown = []
    for n in issue.details.get("rows", [])[:EVIDENCE_ROWS]:
        person = loaded.frame[loaded.id_column].loc[n]
        row = {"row": str(n + 1), "id": repr(person) if person != person.strip() else person}
        if column in loaded.frame:
            row["value"] = loaded.frame[column].loc[n]
        shown.append(row)
    return shown


def add_missing_codes(
    project: Project, dataset: str, codes: list[tuple[str, str]], everywhere: bool
) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    if everywhere:
        if not data.get("missing_codes"):
            data["missing_codes"] = CommentedSeq()
        target = data["missing_codes"]
    else:
        entry = next(d for d in data["datasets"] if d["name"] == dataset)
        if "missing_codes" not in entry:
            # A dataset's own list replaces the project's, so it starts as a copy of it.
            config = dataset_by_name(project.config, dataset)
            known = missing_codes_for(project.config, config)
            entry["missing_codes"] = flow([{"code": m.code, "label": m.label} for m in known])
        target = entry["missing_codes"]
    for value, label in codes:
        target.append(pair("code", value, label))
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def drop_missing_code(project: Project, dataset: str, code: str, everywhere: bool) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    entry = next(d for d in data["datasets"] if d["name"] == dataset)
    if "missing_codes" in entry:
        target = entry["missing_codes"]
    elif everywhere:
        target = data["missing_codes"]
    else:
        # The dataset's own list replaces the project's, so it starts as a copy of it.
        known = project.config.missing_codes
        target = entry["missing_codes"] = flow([{"code": m.code, "label": m.label} for m in known])
    for n in reversed(range(len(target))):
        if str(target[n]["code"]) == code:
            del target[n]
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def add_options(
    project: Project, instrument: str, response_set: str, options: list[tuple[str, str]]
) -> Change:
    relative = project.instrument_files[instrument]
    opened = editing.open_file(project.root, relative)
    data = records.load(opened.text)
    found = next(r for r in data["response_sets"] if r["id"] == response_set)
    for value, label in options:
        found["options"].append(pair("value", value, label))
    return Change(relative, records.dumped(data), opened)


def pair(key: str, value: str, label: str) -> CommentedMap:
    entry = CommentedMap()
    entry.fa.set_flow_style()
    entry[key] = records.scalar(value)
    entry["label"] = records.as_text(label)
    return entry


def replace_at(project: Project, relative: str, path: list[str | int], value: str) -> Change:
    # One value, found by its keys and positions from the top of the file.
    opened = editing.open_file(project.root, relative)
    data = records.load(opened.text)
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = records.as_text(value)
    return Change(relative, records.dumped(data), opened)


def remove_at(project: Project, relative: str, path: list[str | int]) -> Change:
    opened = editing.open_file(project.root, relative)
    data = records.load(opened.text)
    node = data
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return Change(relative, records.dumped(data), opened)
