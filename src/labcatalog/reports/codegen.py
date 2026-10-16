import json
from collections.abc import Callable
from dataclasses import dataclass, field

from labcatalog.config import ProjectConfig, dataset_by_name, missing_codes_for
from labcatalog.resolve import Catalog, ResolvedScore


def scoring_code_r(scores: list[ResolvedScore]) -> str:
    return script(scores, "read.csv()", [], score_lines_r)


def scoring_code_python(scores: list[ResolvedScore]) -> str:
    return script(scores, "pandas.read_csv()", ["import pandas as pd"], score_lines_python)


def script(
    scores: list[ResolvedScore],
    reader: str,
    imports: list[str],
    body: Callable[[ResolvedScore], list[str]],
) -> str:
    # One script for the scores of one instrument in one dataset.
    first = scores[0]
    lines = [
        f"# {first.instrument_id} scores in dataset {first.dataset}; "
        f"d is that dataset read with {reader}",
        *imports,
    ]
    for score in scores:
        lines.append("")
        if score.unavailable_items:
            lines.append(unavailable_note(score))
        else:
            lines += [f"# {score.label} ({score.score_id})", *body(score)]
    return "\n".join(lines)


def score_lines_r(score: ResolvedScore) -> list[str]:
    k, enough = len(score.columns), min_valid(score)
    lines = [
        f"items <- c({quoted(score.columns)})",
        "x <- d[items]",
    ]
    valid_sets = distinct_valid_sets(score)
    if len(valid_sets) == 1:
        lines.append(
            "x[] <- lapply(x, function(v) { v <- suppressWarnings(as.numeric(v)); "
            f"ifelse(v %in% c({numbers(valid_sets[0])}), v, NA) }})"
        )
    else:
        entries = ", ".join(f"{c} = c({numbers(score.valid_values[c])})" for c in score.columns)
        lines.append(f"valid <- list({entries})")
        lines.append(
            "x[] <- Map(function(v, ok) { v <- suppressWarnings(as.numeric(v)); "
            "ifelse(v %in% ok, v, NA) }, x, valid[names(x)])"
        )
    lines += reverse_lines(score, "r")
    lines.append("n_valid <- rowSums(!is.na(x))")
    value = {
        ("complete", "sum"): "rowSums(x)",
        ("complete", "mean"): "rowMeans(x)",
        ("prorate", "sum"): f"rowMeans(x, na.rm = TRUE) * {k}",
        ("prorate", "mean"): "rowMeans(x, na.rm = TRUE)",
        ("zero", "sum"): "rowSums(x, na.rm = TRUE)",
        ("zero", "mean"): f"rowSums(x, na.rm = TRUE) / {k}",
    }[(score.missing_rule, score.method)]
    test = f"n_valid == {k}" if score.missing_rule == "complete" else f"n_valid >= {enough}"
    lines.append(f"d${output_name(score)} <- ifelse({test}, {value}, NA)")
    return lines


def score_lines_python(score: ResolvedScore) -> list[str]:
    k, enough = len(score.columns), min_valid(score)
    lines = [
        f"items = [{quoted(score.columns)}]",
        'x = d[items].apply(pd.to_numeric, errors="coerce")',
    ]
    valid_sets = distinct_valid_sets(score)
    if len(valid_sets) == 1:
        lines.append(f"x = x.where(x.isin([{numbers(valid_sets[0])}]))")
    else:
        entries = ", ".join(f'"{c}": [{numbers(score.valid_values[c])}]' for c in score.columns)
        lines.append(f"valid = {{{entries}}}")
        lines.append("x = x.apply(lambda col: col.where(col.isin(valid[col.name])))")
    lines += reverse_lines(score, "python")
    lines.append("n_valid = x.notna().sum(axis=1)")
    value = {
        ("complete", "sum"): "x.sum(axis=1)",
        ("complete", "mean"): "x.mean(axis=1)",
        ("prorate", "sum"): f"(x.mean(axis=1) * {k})",
        ("prorate", "mean"): "x.mean(axis=1)",
        ("zero", "sum"): "x.fillna(0).sum(axis=1)",
        ("zero", "mean"): f"(x.fillna(0).sum(axis=1) / {k})",
    }[(score.missing_rule, score.method)]
    test = f"n_valid == {k}" if score.missing_rule == "complete" else f"n_valid >= {enough}"
    lines.append(f'd["{output_name(score)}"] = {value}.where({test})')
    return lines


def scoring_snippets(catalog: Catalog) -> dict[tuple[str, str], dict[str, str]]:
    groups: dict[tuple[str, str], list[ResolvedScore]] = {}
    for score in catalog.scores:
        groups.setdefault((score.instrument_id, score.dataset), []).append(score)
    return {
        key: {"r": scoring_code_r(scores), "python": scoring_code_python(scores)}
        for key, scores in groups.items()
    }


@dataclass
class LabelPlan:
    dataset: str
    missing: list[tuple[float, str]]
    option_sets: list[list[tuple[float, str]]] = field(default_factory=list)
    # Column, its label, and which option set (or None) labels its values.
    columns: list[tuple[str, str, int | None]] = field(default_factory=list)
    numeric: set[str] = field(default_factory=set)


def label_plan(config: ProjectConfig, catalog: Catalog, dataset_name: str) -> LabelPlan:
    dataset = dataset_by_name(config, dataset_name)
    # Text codes such as "" cannot sit beside numeric values in one labelled column.
    missing = [
        (code, m.label)
        for m in missing_codes_for(config, dataset)
        if (code := as_number(m.code)) is not None
    ]
    plan = LabelPlan(dataset=dataset_name, missing=missing)
    for variable in catalog.variables_for(dataset_name):
        options = [(as_number(o.value), o.label) for o in variable.response_options]
        index = None
        if options and all(value is not None for value, _ in options):
            if options not in plan.option_sets:
                plan.option_sets.append(options)
            index = plan.option_sets.index(options)
        plan.columns.append((variable.column, " / ".join(variable.text.values()), index))
        if variable.type == "number" or index is not None:
            plan.numeric.add(variable.column)
    for score in catalog.scores_for(dataset_name):
        if score.existing_column:
            label = f"{score.label} ({score.instrument_id})"
            plan.columns.append((score.existing_column, label, None))
            plan.numeric.add(score.existing_column)
    return plan


def label_code_r(plan: LabelPlan) -> str:
    lines = [
        f"# Labels for {plan.dataset}; d is that dataset read with read.csv(). Needs the haven package.",
        "library(haven)",
        f"missing <- {r_vector(plan.missing)}",
    ]
    lines += [f"options_{n} <- {r_vector(o)}" for n, o in enumerate(plan.option_sets, start=1)]
    lines += [
        "label_column <- function(x, label, labels = NULL) {",
        "  if (!is.numeric(x)) return(structure(x, label = label))",
        "  labelled_spss(x, labels = c(labels, missing), na_values = unname(missing), label = label)",
        "}",
    ]
    for column, label, index in plan.columns:
        target = f"d[[{text(column)}]]"
        options = "" if index is None else f", options_{index + 1}"
        lines.append(f"{target} <- label_column({target}, {text(label)}{options})")
    return "\n".join(lines)


def label_code_python(plan: LabelPlan) -> str:
    save = "column_labels=column_labels, variable_value_labels=variable_value_labels"
    if plan.missing:
        save += ", missing_ranges=missing_ranges"
    lines = [
        f"# Labels for {plan.dataset}; d is that dataset read with pandas.read_csv().",
        f'# To save them with the data: pyreadstat.write_sav(d, "{plan.dataset}.sav", {save})',
        "import numpy as np",
        "",
        f"missing_codes = {python_dict(plan.missing)}",
    ]
    lines += [f"options_{n} = {python_dict(o)}" for n, o in enumerate(plan.option_sets, start=1)]
    lines.append("column_labels = {")
    lines += [f"    {text(column)}: {text(label)}," for column, label, _ in plan.columns]
    lines.append("}")
    lines.append("variable_value_labels = {")
    for column, _, index in plan.columns:
        parts = ([] if index is None else [f"**options_{index + 1}"]) + (
            ["**missing_codes"] if plan.missing and column in plan.numeric else []
        )
        if parts:
            value = parts[0].removeprefix("**") if len(parts) == 1 else f"{{{', '.join(parts)}}}"
            lines.append(f"    {text(column)}: {value},")
    lines.append("}")
    if plan.missing:
        lines += [
            "missing_ranges = {column: list(missing_codes) for column in variable_value_labels}",
            "# After saving, missing codes become NaN for analysis in Python.",
            "d = d.replace({column: {code: np.nan for code in missing_codes} for column in missing_ranges})",
        ]
    return "\n".join(lines)


def label_snippets(config: ProjectConfig, catalog: Catalog) -> dict[str, dict[str, str]]:
    snippets = {}
    for dataset in config.datasets:
        plan = label_plan(config, catalog, dataset.name)
        snippets[dataset.name] = {"r": label_code_r(plan), "python": label_code_python(plan)}
    return snippets


def r_vector(pairs: list[tuple[float, str]]) -> str:
    if not pairs:
        return "NULL"
    return "c(" + ", ".join(f"{text(label)} = {number(value)}" for value, label in pairs) + ")"


def python_dict(pairs: list[tuple[float, str]]) -> str:
    return "{" + ", ".join(f"{number(value)}: {text(label)}" for value, label in pairs) + "}"


def text(value: str) -> str:
    # A JSON string is also a valid string literal in R and in Python.
    return json.dumps(value, ensure_ascii=False)


def as_number(value: int | float | str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def reverse_lines(score: ResolvedScore, language: str) -> list[str]:
    if not score.reverse_columns:
        return []
    if score.reversed_in_data:
        return ["# Reverse-keyed items are already reversed in this dataset."]
    groups: dict[tuple[float, float], list[str]] = {}
    for column in score.reverse_columns:
        groups.setdefault(score.reverse_bounds[column], []).append(column)
    lines = []
    for (low, high), columns in groups.items():
        target = f"c({quoted(columns)})" if language == "r" else f"[{quoted(columns)}]"
        if language == "r":
            lines.append(f"x[{target}] <- {number(low + high)} - x[{target}]")
        else:
            lines.append(f"x[{target}] = {number(low + high)} - x[{target}]")
    return lines


def unavailable_note(score: ResolvedScore) -> str:
    missing = ", ".join(score.unavailable_items)
    return f"# {score.label} cannot be computed in {score.dataset}: no data for {missing}"


def output_name(score: ResolvedScore) -> str:
    return f"{score.score_id}_{score.dataset}"


def min_valid(score: ResolvedScore) -> int:
    return score.min_valid or len(score.columns)


def distinct_valid_sets(score: ResolvedScore) -> list[list[float]]:
    sets: list[list[float]] = []
    for column in score.columns:
        values = sorted(score.valid_values[column])
        if values not in sets:
            sets.append(values)
    return sets


def quoted(columns: list[str]) -> str:
    return ", ".join(f'"{column}"' for column in columns)


def numbers(values: list[float]) -> str:
    return ", ".join(number(value) for value in values)


def number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))
