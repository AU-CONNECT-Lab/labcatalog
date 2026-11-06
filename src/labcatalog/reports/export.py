from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from labcatalog.config import (
    DatasetConfig,
    ProjectConfig,
    dataset_by_name,
    id_column_for,
    missing_codes_for,
    roster_dataset,
    roster_name,
    rosters,
)
from labcatalog.data.resolve import ResolvedScore, ResolvedVariable
from labcatalog.data.scoring import scorable
from labcatalog.exceptions import ExportError
from labcatalog.metadata.browse import build_index, matches
from labcatalog.pipeline import CatalogResult
from labcatalog.reports.codebook_doc import CODEBOOK, codebook_docx
from labcatalog.reports.codegen import output_name
from labcatalog.reports.outputs import write_output
from labcatalog.stats.analysis import linkable
from labcatalog.stats.cfa import CfaFit
from labcatalog.stats.summary import VariableSummary

VARIABLES = "variables.csv"
SCORE_STATISTICS = "score_statistics.csv"
ITEM_STATISTICS = "item_statistics.csv"
# One file per dataset, or one wide table with a row per person or per group.
BY_DATASET = "dataset"
BY_ID = "id"
BY_GROUP = "group"
# The first column of a wide table, since IDs belong to their study.
STUDY = "study"
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
        missing = missing_text(config, dataset_by_name(config, dataset))
        rows += [
            item_row(result, variable, missing)
            for variable in result.catalog.variables_for(dataset)
            if variable.instrument_id in instrument_ids
        ]
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


def roster_variable_rows(result: CatalogResult, studies: Sequence[str]) -> list[dict[str, str]]:
    config = result.project.config
    rows = []
    for study in studies:
        missing = missing_text(config, roster_dataset(config, study))
        rows += [item_row(result, v, missing) for v in roster_variables(result, study)]
    return [{column: row.get(column, "") for column in COLUMNS} for row in rows]


def item_row(result: CatalogResult, variable: ResolvedVariable, missing: str) -> dict[str, str]:
    instrument = result.project.instruments[variable.instrument_id]
    return {
        "dataset": variable.dataset,
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


def missing_text(config: ProjectConfig, dataset: DatasetConfig) -> str:
    return "; ".join(f"{c.code}={c.label}" for c in missing_codes_for(config, dataset))


def roster_studies(result: CatalogResult, instrument_ids: Sequence[str]) -> list[str]:
    # The studies whose participant roster one of these instruments describes.
    return [
        study
        for study, roster in rosters(result.project.config).items()
        if roster.instrument in instrument_ids and study in result.rosters
    ]


def roster_variables(result: CatalogResult, study: str) -> list[ResolvedVariable]:
    return [v for v in result.catalog.roster_variables if v.dataset == roster_name(study)]


def roster_frame(result: CatalogResult, study: str) -> pd.DataFrame:
    loaded = result.rosters[study]
    roster = result.project.config.studies[study].roster
    keys = [loaded.id_column, roster.group_column, roster.role_column]
    # Open answers stay out, as in the datasets' files.
    items = [v.column for v in roster_variables(result, study) if v.type != "text"]
    return loaded.frame[[c for c in dict.fromkeys(keys) if c] + items]


def score_statistics(
    result: CatalogResult, plan: dict[str, list[str]], fits: Sequence[CfaFit] = ()
) -> list[dict]:
    found = {s.key: s for s in result.summary.scores}
    omega = {(f.instrument_id, f.dataset, s): v for f in fits for s, v in f.omega.items()}
    rows = []
    for dataset, instrument_ids in plan.items():
        info = result.datasets[dataset].config
        for score in exported_scores(result, dataset, instrument_ids):
            stats = found[score.key]
            low, high = stats.possible_range
            rows.append(
                {
                    "dataset": dataset,
                    "study": info.study,
                    "wave": info.wave,
                    "reporter": info.reporter,
                    "column": output_name(score),
                    "instrument": score.instrument_id,
                    "score": score.score_id,
                    "label": score.label,
                    "n": stats.n_valid,
                    "n_complete": stats.n_complete,
                    "mean": stats.mean,
                    "sd": stats.sd,
                    "median": stats.median,
                    "min": stats.minimum,
                    "max": stats.maximum,
                    "possible_min": low,
                    "possible_max": high,
                    "alpha": stats.alpha,
                    # Only as fitted by the window's factor models; empty otherwise.
                    "omega": omega.get((score.instrument_id, dataset, score.score_id), ""),
                }
            )
    return rows


def item_statistics(result: CatalogResult, plan: dict[str, list[str]]) -> list[dict]:
    given = [
        v
        for dataset, instrument_ids in plan.items()
        for v in result.catalog.variables_for(dataset)
        if v.instrument_id in instrument_ids
    ]
    return item_statistics_of(given, result.summary.variables)


def roster_item_statistics(result: CatalogResult, studies: Sequence[str]) -> list[dict]:
    given = [v for study in studies for v in roster_variables(result, study)]
    return item_statistics_of(given, result.summary.roster)


def item_statistics_of(
    variables: list[ResolvedVariable], summaries: list[VariableSummary]
) -> list[dict]:
    found = {(v.dataset, v.column): v for v in summaries}
    rows = []
    for variable in variables:
        stats = found.get((variable.dataset, variable.column))
        # Open answers stay out, as in the data files.
        if variable.type == "text" or not stats:
            continue
        rows.append(
            {
                "dataset": variable.dataset,
                "study": variable.study,
                "wave": variable.wave,
                "reporter": variable.reporter,
                "column": variable.column,
                "instrument": variable.instrument_id,
                "item": variable.item_id,
                "type": variable.type,
                "n": stats.n_valid,
                "missing": "; ".join(f"{k}={n}" for k, n in stats.missing.items() if n),
                "not_an_option": stats.n_unexpected,
                "mean": stats.mean,
                "sd": stats.sd,
                "median": stats.median,
                "min": stats.minimum,
                "max": stats.maximum,
                "counts": "; ".join(f"{k}={n}" for k, n in stats.value_counts.items()),
            }
        )
    return rows


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
    keys = [
        id_column_for(result.project.config, config),
        config.respondent_column,
        config.date_column,
    ]
    # Open answers are never shown or exported, since they can identify people.
    items = [
        v.column
        for v in result.catalog.variables_for(dataset)
        if v.instrument_id in instrument_ids and v.type != "text"
    ]
    frame = loaded.frame[[c for c in dict.fromkeys(keys) if c] + items].copy()
    group = result.project.config.ids.group
    # A group read from the roster is not in the data, so it goes next to the ID.
    roster = result.project.config.studies[loaded.config.study].roster
    if roster and group and loaded.group is not None:
        frame.insert(1, group.name, loaded.group)
    for score in exported_scores(result, dataset, instrument_ids):
        frame[output_name(score)] = result.scores[dataset][score.key]
    return frame


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
    if not plan and datasets:
        raise ExportError("None of these instruments is in these datasets")
    # An instrument of the participant roster is in no dataset but is still exported.
    if not plan and not roster_studies(result, instrument_ids):
        raise ExportError("None of these instruments is given in a dataset or a participant roster")
    return plan


def layouts(result: CatalogResult, plan: dict[str, list[str]]) -> list[str]:
    grouped = all(result.datasets[d].group is not None for d in plan)
    return [BY_DATASET, BY_ID, *([BY_GROUP] if grouped else [])]


def write_export(
    result: CatalogResult,
    plan: dict[str, list[str]],
    layout: str,
    fits: Sequence[CfaFit] = (),
    data: bool = True,
    statistics: bool = True,
    codebook: bool = True,
    studies: Sequence[str] = (),
) -> Export:
    # studies are those whose participant roster goes into a file of its own.
    allowed = layouts(result, plan)
    if data and plan and layout not in allowed:
        raise ExportError(f"Cannot export by {layout}; these datasets allow {', '.join(allowed)}")
    variables = variable_rows(result, plan)
    scores = score_statistics(result, plan, fits) if statistics else None
    items = item_statistics(result, plan) if statistics else []
    frames, left_out, data_files = {}, {}, {}
    if data and plan and layout == BY_DATASET:
        frames = {f"{d}.csv": data_frame(result, d, ids) for d, ids in plan.items()}
        data_files = {d: f"{d}.csv" for d in plan}
    elif data and plan:
        wide, left_out = wide_frame(result, plan, layout)
        name = f"data_by_{key_name(result, layout)}.csv"
        frames = {name: wide}
        data_files = dict.fromkeys(plan, name)
        for row in [*variables, *(scores or []), *items]:
            row["column"] = f"{row['dataset']}_{row['column']}"
    # A roster keeps its own file and column names, whatever the layout.
    variables += roster_variable_rows(result, studies)
    items += roster_item_statistics(result, studies) if statistics else []
    for study in studies if data else []:
        name = f"{roster_name(study)}.csv"
        frames[name] = roster_frame(result, study)
        data_files[roster_name(study)] = name
    tables = {VARIABLES: pd.DataFrame(variables, columns=COLUMNS)}
    if scores is not None:
        tables |= {SCORE_STATISTICS: pd.DataFrame(scores), ITEM_STATISTICS: pd.DataFrame(items)}
    # The byte-order mark makes Excel open the lists as UTF-8; data files stay plain for R.
    files = {name: t.to_csv(index=False).encode("utf-8-sig") for name, t in tables.items()}
    files |= {name: frame.to_csv(index=False).encode("utf-8") for name, frame in frames.items()}
    if codebook:
        files[CODEBOOK] = codebook_docx(result, plan, variables, scores, data_files, studies)
    folder = write_output(result.project.root, "export", files, result.manifest)
    return Export(folder, left_out)


def key_name(result: CatalogResult, layout: str) -> str:
    return result.project.config.ids.group.name if layout == BY_GROUP else "id"


def wide_frame(
    result: CatalogResult, plan: dict[str, list[str]], layout: str
) -> tuple[pd.DataFrame, dict[str, int]]:
    # One row per person or group of a study; a row whose key repeats within a file cannot be placed.
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
        elif key_name(result, layout) in frame:
            frame = frame.drop(columns=key_name(result, layout))
        frame = frame.add_prefix(f"{dataset}_")[keep]
        study = [loaded.config.study] * int(keep.sum())
        parts.append(frame.set_axis(pd.MultiIndex.from_arrays([study, keys[keep].to_numpy()])))
    wide = pd.concat(parts, axis=1).sort_index()
    return wide.rename_axis([STUDY, key_name(result, layout)]).reset_index(), left_out
