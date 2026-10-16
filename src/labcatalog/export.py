from datetime import datetime
from pathlib import Path

import pandas as pd

from labcatalog.codegen import output_name
from labcatalog.config import dataset_by_name, id_column_for, missing_codes_for
from labcatalog.pipeline import CatalogResult
from labcatalog.resolve import ResolvedScore
from labcatalog.scoring import scorable

VARIABLES = "variables.csv"
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


def write_export(result: CatalogResult, plan: dict[str, list[str]], parent: Path) -> Path:
    folder = parent / f"labcatalog_export_{datetime.now():%Y-%m-%d_%H%M%S}"
    folder.mkdir()
    # The byte-order mark makes Excel open the list as UTF-8; data files stay plain for R.
    pd.DataFrame(variable_rows(result, plan), columns=COLUMNS).to_csv(
        folder / VARIABLES, index=False, encoding="utf-8-sig"
    )
    for dataset, instrument_ids in plan.items():
        data_frame(result, dataset, instrument_ids).to_csv(folder / f"{dataset}.csv", index=False)
    return folder
