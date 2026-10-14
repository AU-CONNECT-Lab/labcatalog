from labcatalog.resolve import Catalog, ResolvedScore


def score_code_r(score: ResolvedScore) -> str:
    if score.unavailable_items:
        return unavailable_note(score)
    k, enough = len(score.columns), min_valid(score)
    lines = [
        header(score, "read.csv()"),
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
    return "\n".join(lines)


def score_code_python(score: ResolvedScore) -> str:
    if score.unavailable_items:
        return unavailable_note(score)
    k, enough = len(score.columns), min_valid(score)
    lines = [
        header(score, "pandas.read_csv()"),
        "import pandas as pd",
        "",
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
    return "\n".join(lines)


def scoring_snippets(catalog: Catalog) -> dict[str, dict[str, str]]:
    return {
        score.key: {"r": score_code_r(score), "python": score_code_python(score)}
        for score in catalog.scores
    }


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


def header(score: ResolvedScore, reader: str) -> str:
    return (
        f"# {score.label} ({score.instrument_id}.{score.score_id}), dataset {score.dataset}; "
        f"d is that dataset read with {reader}"
    )


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
