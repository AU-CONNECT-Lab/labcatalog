import csv
import difflib
import io

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.config import dataset_by_name
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing, records
from labcatalog.metadata.changes import Change
from labcatalog.project import Project

# Chosen for an unmapped item that was not asked in that dataset.
NOT_ASKED = "-"


def closest(word: str, choices: list[str]) -> str | None:
    found = difflib.get_close_matches(word, choices, n=1, cutoff=0.6)
    return found[0] if found else None


def map_rows(project: Project, dataset: str, rows: list[tuple[str, str, str]]) -> Change:
    # New rows go at the end of the dataset's column map; the rows already there stay as written.
    relative = f"{defaults.MAPS_DIR}/{dataset}.csv"
    opened = editing.open_file(project.root, relative)
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    text = opened.text.rstrip("\n") + "\n" + out.getvalue()
    return Change(relative, text, opened)


def add_to_vocab(project: Project, kind: str, value: str) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    if not data.get("vocab"):
        data["vocab"] = CommentedMap()
    vocab = data["vocab"]
    if kind not in vocab:
        # Written out in full, so the words that applied by default still apply.
        vocab[kind] = flow(getattr(project.config.vocab, kind))
    vocab[kind].append(value)
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def replace_word(project: Project, details: dict, word: str) -> Change:
    # The one entry that holds the word: a dataset in the settings or an administration.
    field = details["field"]
    if "dataset" in details:
        relative = defaults.CONFIG_FILENAME
        opened = editing.open_file(project.root, relative)
        data = records.load(opened.text)
        entry = next(d for d in data["datasets"] if d["name"] == details["dataset"])
    else:
        relative = project.study_files[details["study"]]
        opened = editing.open_file(project.root, relative)
        data = records.load(opened.text)
        entry = data["administrations"][details["administration"]]
    entry[field] = records.as_text(word)
    return Change(relative, records.dumped(data), opened)


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
    listed = {entry.column for entry in project.maps.get(dataset, [])}
    return [c for c in columns if c not in listed]


def flow(values: list[str]) -> CommentedSeq:
    seq = CommentedSeq(values)
    seq.fa.set_flow_style()
    return seq
