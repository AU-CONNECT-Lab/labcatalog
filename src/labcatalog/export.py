from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from labcatalog.browse import build_index, matches
from labcatalog.codegen import output_name
from labcatalog.config import dataset_by_name, id_column_for, missing_codes_for
from labcatalog.exceptions import ExportError, MetadataError
from labcatalog.outputs import write_output
from labcatalog.pipeline import CatalogResult, run_catalog
from labcatalog.resolve import ResolvedScore
from labcatalog.scoring import scorable
from labcatalog.stats.analysis import linkable

VARIABLES = "variables.csv"
# One file per dataset, or one wide table with a row per person or per group.
BY_DATASET = "dataset"
BY_ID = "id"
BY_GROUP = "group"
COLUMNS = [
    "dataset",
    "study",
    "wave",
    "reporter",
    "target",
    "column",
    "instrument",
    "abbreviation",
    "kind",
    "item",
    "text",
    "type",
    "options",
    "reverse",
    "min",
    "max",
    "missing_codes",
    "score_items",
    "missing_rule",
    "in_data",
]


@dataclass
class Export:
    folder: Path
    # Rows per dataset left out of a wide table because their key repeats in that file.
    left_out: dict[str, int]


def export_plan(
    result: CatalogResult, found: dict[str, list[str]], chosen: set[str]
) -> dict[str, list[str]]:
    # Each dataset, in labcatalog.yaml order, to the chosen instruments the filters found in it.
    plan = {}
    for dataset in result.project.config.datasets:
        instruments = [i for i in found if i in chosen and dataset.name in found[i]]
        if instruments:
            plan[dataset.name] = instruments
    return plan


def variable_rows(result: CatalogResult, plan: dict[str, list[str]]) -> list[dict[str, str]]:
    config = result.project.config
    rows = []
    for dataset, instrument_ids in plan.items():
        missing = "; ".join(
            f"{c.code}={c.label}"
            for c in missing_codes_for(config, dataset_by_name(config, dataset))
        )
        for variable in result.catalog.variables_for(dataset):
            if variable.instrument_id not in instrument_ids:
                continue
            instrument = result.project.instruments[variable.instrument_id]
            rows.append(
                {
                    "dataset": dataset,
                    "study": variable.study,
                    "wave": variable.wave,
                    "reporter": variable.reporter,
                    "target": variable.target or "",
                    "column": variable.column,
                    "instrument": variable.instrument_id,
                    "abbreviation": instrument.abbreviation or "",
                    "kind": "item",
                    "item": variable.item_id,
                    "text": " / ".join(variable.text.values()),
                    "type": variable.type,
                    "options": "; ".join(f"{o.value}={o.label}" for o in variable.response_options),
                    "reverse": "yes" if variable.reverse else "",
                    "min": number_text(variable.allowed_min),
                    "max": number_text(variable.allowed_max),
                    "missing_codes": missing,
                    "in_data": "no" if variable.type == "text" else "yes",
                }
            )
        for score in exported_scores(result, dataset, instrument_ids):
            instrument = result.project.instruments[score.instrument_id]
            definition = next(s for s in instrument.scores if s.id == score.score_id)
            info = result.datasets[dataset].config
            rows.append(
                {
                    "dataset": dataset,
                    "study": info.study,
                    "wave": info.wave,
                    "reporter": info.reporter,
                    "column": output_name(score),
                    "instrument": score.instrument_id,
                    "abbreviation": instrument.abbreviation or "",
                    "kind": "score",
                    "item": score.score_id,
                    "text": score.label,
                    "type": score.method,
                    "score_items": "; ".join(definition.items),
                    "missing_rule": score.missing_rule,
                    "in_data": "yes",
                }
            )
    return [{column: row.get(column, "") for column in COLUMNS} for row in rows]


def number_text(value: float | None) -> str:
    return "" if value is None else f"{value:g}"


def exported_scores(
    result: CatalogResult, dataset: str, instrument_ids: list[str]
) -> list[ResolvedScore]:
    loaded = result.datasets[dataset]
    return [
        s
        for s in result.catalog.scores_for(dataset)
        if s.instrument_id in instrument_ids and scorable(loaded, s)
    ]


def data_frame(result: CatalogResult, dataset: str, instrument_ids: list[str]) -> pd.DataFrame:
    loaded = result.datasets[dataset]
    config = loaded.config
    keys = [id_column_for(result.project.config, config), config.group_column, config.date_column]
    # Open answers are never shown or exported, since they can identify people.
    items = [
        v.column
        for v in result.catalog.variables_for(dataset)
        if v.instrument_id in instrument_ids and v.type != "text"
    ]
    frame = loaded.frame[[c for c in dict.fromkeys(keys) if c] + items].copy()
    for score in exported_scores(result, dataset, instrument_ids):
        frame[output_name(score)] = result.scores[dataset][score.key]
    return frame


def run_export(root: Path, instrument_ids: list[str], datasets: list[str], layout: str) -> Export:
    result = run_catalog(root)
    if result.project is None:
        raise MetadataError(result.report.issues)
    return write_export(result, named_plan(result, instrument_ids, datasets), layout)


def named_plan(
    result: CatalogResult, instrument_ids: list[str], datasets: list[str]
) -> dict[str, list[str]]:
    # Without dataset names, every dataset that gives one of the instruments.
    project = result.project
    unknown = [i for i in instrument_ids if i not in project.instruments]
    unknown += [d for d in datasets if d not in {c.name for c in project.config.datasets}]
    if unknown:
        raise ExportError(f"Not an instrument or dataset in this project: {', '.join(unknown)}")
    plan = export_plan(result, matches(build_index(project), {}), set(instrument_ids))
    plan = {d: ids for d, ids in plan.items() if not datasets or d in datasets}
    if not plan:
        raise ExportError("None of these instruments is in these datasets")
    return plan


def layouts(result: CatalogResult, plan: dict[str, list[str]]) -> list[str]:
    grouped = all(result.datasets[d].group is not None for d in plan)
    return [BY_DATASET, BY_ID, *([BY_GROUP] if grouped else [])]


def write_export(result: CatalogResult, plan: dict[str, list[str]], layout: str) -> Export:
    allowed = layouts(result, plan)
    if layout not in allowed:
        raise ExportError(f"Cannot export by {layout}; these datasets allow {', '.join(allowed)}")
    variables = pd.DataFrame(variable_rows(result, plan), columns=COLUMNS)
    if layout == BY_DATASET:
        frames = {f"{d}.csv": data_frame(result, d, ids) for d, ids in plan.items()}
        left_out = {}
    else:
        wide, left_out = wide_frame(result, plan, layout)
        frames = {f"data_by_{key_name(result, layout)}.csv": wide}
        variables["column"] = variables["dataset"] + "_" + variables["column"]
    # The byte-order mark makes Excel open the list as UTF-8; data files stay plain for R.
    files = {VARIABLES: variables.to_csv(index=False).encode("utf-8-sig")}
    files |= {name: frame.to_csv(index=False).encode("utf-8") for name, frame in frames.items()}
    folder = write_output(result.project.root, "export", files, result.manifest)
    return Export(folder, left_out)


def key_name(result: CatalogResult, layout: str) -> str:
    return result.project.config.ids.group.name if layout == BY_GROUP else "id"


def wide_frame(
    result: CatalogResult, plan: dict[str, list[str]], layout: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    # One row per person or group; a row whose key repeats within a file cannot be placed.
    parts = []
    left_out = {}
    for dataset, instrument_ids in plan.items():
        loaded = result.datasets[dataset]
        keys = (loaded.group if layout == BY_GROUP else loaded.frame[loaded.id_column]).astype(
            "string"
        )
        keep = linkable(keys)
        if (~keep).sum():
            left_out[dataset] = int((~keep).sum())
        frame = data_frame(result, dataset, instrument_ids)
        if layout == BY_ID:
            frame = frame.drop(columns=loaded.id_column)
        frame = frame.add_prefix(f"{dataset}_")[keep]
        parts.append(frame.set_axis(keys[keep].to_numpy()))
    wide = pd.concat(parts, axis=1).sort_index()
    return wide.rename_axis(key_name(result, layout)).reset_index(), left_out
