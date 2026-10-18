import subprocess
import textwrap
from itertools import combinations
from pathlib import Path

import pandas as pd

from labcatalog.exceptions import MplusError
from labcatalog.stats.cfa import (
    ESTIMATORS,
    SECOND_ORDER,
    SUBSCALE_SCORES,
    WLSMV,
    CfaModel,
    covariate_names,
    lavaan_names,
    model_estimator,
)
from labcatalog.stats.invariance import (
    GROUP_COLUMN,
    InvarianceModel,
    is_grouped,
    occasion_name,
    side_by_side,
    stacked,
)

MISSING = -999
# Mplus reads at most 90 characters a line.
WIDTH = 80
# Mplus's usual sequence; it has no step for thresholds alone, as Wu and Estabrook's in R.
STEPS = ("configural", "metric", "scalar")
DATA = "mplus_invariance.dat"


def cfa_files(models: list[CfaModel], estimator: str, title: str) -> dict[str, str]:
    files = {}
    for n, model in enumerate(models, start=1):
        name = f"mplus_cfa_{n}"
        files[f"{name}.inp"] = cfa_input(model, f"{name}.dat", estimator, title)
        items, _ = lavaan_names(model)
        files[f"{name}.dat"] = data_text(model.data[[*items, *model.covariates]])
    return files


def data_text(data: pd.DataFrame) -> str:
    # Free format without a header, as Mplus expects.
    return data.fillna(MISSING).to_csv(sep=" ", header=False, index=False, float_format="%g")


def cfa_input(model: CfaModel, data_file: str, estimator: str, title: str) -> str:
    items, factors = lavaan_names(model)
    covariates = covariate_names(model)
    names = f"x1-x{len(items)}"
    ordered = model_estimator(model, estimator) == WLSMV
    what = "Subscale scores" if model.kind == SUBSCALE_SCORES else ITEMS
    lines = [
        *title_lines(f"{title}, {model.dataset}, {model.kind} model"),
        f"! {what}:",
        *(f"! {name} = {column}"[:WIDTH] for column, name in items.items()),
        *(f"! {name} = {column}, a covariate"[:WIDTH] for column, name in covariates.items()),
        "DATA:",
        f'  FILE = "{data_file}";',
        "VARIABLE:",
        *statement(f"NAMES = {' '.join([names, *covariates.values()])}"),
        *([f"  CATEGORICAL = {names};"] if ordered else []),
        f"  MISSING = ALL ({MISSING});",
        "ANALYSIS:",
        f"  ESTIMATOR = {ESTIMATORS[model_estimator(model, estimator)]};",
        "MODEL:",
    ]
    # Loadings free and factor variances fixed at 1, as lavaan's std.lv.
    for score, columns in model.factors.items():
        first, *rest = (items[c] for c in columns)
        lines += statement(f"{factors[score]} BY {' '.join([first + '*', *rest])}")
    first_order = [factors[score] for score in model.factors]
    lines += statement(f"{' '.join(first_order)}@1")
    if model.kind == SECOND_ORDER:
        first, *rest = first_order
        lines += statement(f"g BY {' '.join([first + '*', *rest])}")
        lines += statement("g@1")
    if covariates:
        # Regressed factors' residual covariances, written out rather than left to defaults.
        lines += statement(f"{' '.join(first_order)} ON {' '.join(covariates.values())}")
        lines += [s for a, b in combinations(first_order, 2) for s in statement(f"{a} WITH {b}")]
    lines += ["OUTPUT:", "  STDYX;", ""]
    return "\n".join(lines)


ITEMS = "Items, with reverse-scored items already reversed"


def title_lines(heading: str) -> list[str]:
    # A colon would read as the start of the next command.
    text = f"{heading}, written by labcatalog".replace(":", ",")
    return ["TITLE:", *textwrap.wrap(text, WIDTH, initial_indent="  ", subsequent_indent="  ")]


def statement(text: str) -> list[str]:
    return textwrap.wrap(f"{text};", WIDTH, initial_indent="  ", subsequent_indent="    ")


def invariance_files(model: InvarianceModel, estimator: str, title: str) -> dict[str, str]:
    items = list(next(iter(model.occasions.values())).columns)
    columns = {item: f"x{i}" for i, item in enumerate(items, start=1)}
    item_lines = [f"! {x} = {item}"[:WIDTH] for item, x in columns.items()]
    if is_grouped(model.across):
        data, _ = stacked(model, columns)
        codes = {key: n for n, key in enumerate(model.occasions, start=1)}
        data[GROUP_COLUMN] = data[GROUP_COLUMN].map(codes)
        text = grouped_input(model, columns, item_lines, estimator, title)
        return {"mplus_invariance.inp": text, DATA: data_text(data)}
    data, _ = side_by_side(model, columns)
    files = {DATA: data_text(data)}
    for k, step in enumerate(STEPS, start=1):
        text = longitudinal_input(model, columns, item_lines, estimator, title, step)
        files[f"mplus_invariance_{k}_{step}.inp"] = text
    return files


def grouped_input(
    model: InvarianceModel,
    columns: dict[str, str],
    item_lines: list[str],
    estimator: str,
    title: str,
) -> str:
    ordered = estimator == WLSMV
    names = list(columns.values())
    codes = " ".join(f"{n} = g{n}" for n in range(1, len(model.occasions) + 1))
    binary = ordered and any(
        len(set().union(*(set(f[item]) for f in model.occasions.values()))) == 2 for item in columns
    )
    lines = [
        *title_lines(f"{title}, invariance across {model.across}"),
        f"! {ITEMS}:",
        *item_lines,
        *(f"! g{n} = {key}"[:WIDTH] for n, key in enumerate(model.occasions, start=1)),
        "! Mplus fits and compares the steps itself.",
        *(
            [
                "! Its metric step frees the thresholds, so it differs from the metric step",
                "! of labcatalog's tables, which holds them equal.",
            ]
            if ordered
            else []
        ),
        *freed_lines(model, applied=False),
        "DATA:",
        f'  FILE = "{DATA}";',
        "VARIABLE:",
        *statement(f"NAMES = {' '.join(names)} {GROUP_COLUMN}"),
        *statement(f"USEVARIABLES = {' '.join(names)}"),
        *(statement(f"CATEGORICAL = {' '.join(names)}") if ordered else []),
        f"  GROUPING = {GROUP_COLUMN} ({codes});",
        f"  MISSING = ALL ({MISSING});",
        "ANALYSIS:",
        *estimator_lines(estimator),
        # Mplus has no metric step for binary items with WLSMV.
        f"  MODEL = {'CONFIGURAL SCALAR' if binary else 'CONFIGURAL METRIC SCALAR'};",
        "MODEL:",
    ]
    for j, members in enumerate(model.factors.values(), start=1):
        lines += statement(f"f{j} BY {' '.join(columns[item] for item in members)}")
    lines += ["OUTPUT:", "  STDYX;", ""]
    return "\n".join(lines)


def longitudinal_input(
    model: InvarianceModel,
    columns: dict[str, str],
    item_lines: list[str],
    estimator: str,
    title: str,
    step: str,
) -> str:
    ordered = estimator == WLSMV
    times = range(1, len(model.occasions) + 1)
    names = [f"{x}_t{t}" for t in times for x in columns.values()]
    k = STEPS.index(step) + 1
    freed = {(f.item, f.parameter) for f in model.freed}
    equal_loadings = step != "configural"
    # For ordered items, freeing an intercept as in R frees the item's thresholds here.
    equal_levels = step == "scalar"
    level = "threshold" if ordered else "intercept"
    lines = [
        *title_lines(f"{title}, invariance across {model.across}, {step} step"),
        f"! {ITEMS}; _t<n> is the occasion:",
        *item_lines,
        *(
            f"! t{t} = {occasion_name(model.across, key)}"[:WIDTH]
            for t, key in zip(times, model.occasions, strict=True)
        ),
        "! Mplus's usual steps: configural, metric (equal loadings), scalar (equal loadings",
        f"! and {level}s); run them in order, as each compares itself with the one before.",
        *(
            ["! The metric step here frees the thresholds, unlike labcatalog's tables."]
            if ordered
            else []
        ),
        *freed_lines(model, applied=True),
        "DATA:",
        f'  FILE = "{DATA}";',
        "VARIABLE:",
        *statement(f"NAMES = {' '.join(names)}"),
        *(statement(f"CATEGORICAL = {' '.join(names)}") if ordered else []),
        f"  MISSING = ALL ({MISSING});",
        "ANALYSIS:",
        *estimator_lines(estimator),
        *([f"  DIFFTEST = {STEPS[k - 2]}.dif;"] if ordered and k > 1 else []),
        "MODEL:",
    ]
    for t in times:
        for j, members in enumerate(model.factors.values(), start=1):
            for item in members:
                x = columns[item]
                same = equal_loadings and (item, "loading") not in freed
                lines.append(f"  f{j}_t{t} BY {x}_t{t}*{f' (l{x[1:]})' if same else ''};")
    for t in times:
        for j in range(1, len(model.factors) + 1):
            # Factors on the first occasion set the scale; later ones vary once loadings hold.
            later = t > 1
            lines.append(f"  f{j}_t{t}{'*' if later and equal_loadings else '@1'};")
            lines.append(f"  [f{j}_t{t}{'*' if later and equal_levels else '@0'}];")
    for item, x in columns.items():
        # As in R, freed thresholds count only for ordered items.
        loose = {(item, "intercept")} | ({(item, "threshold")} if ordered else set())
        held = equal_levels and not freed & loose
        thresholds = len(set().union(*(set(f[item].dropna()) for f in model.occasions.values())))
        for t in times:
            if ordered:
                if held:
                    lines += [f"  [{x}_t{t}${c}] (t{x[1:]}_{c});" for c in range(1, thresholds)]
                # Latent response variances: 1 on the first occasion, free later once held.
                lines.append(f"  {x}_t{t}{'*' if held and t > 1 else '@1'};")
            elif held:
                lines.append(f"  [{x}_t{t}] (i{x[1:]});")
    # The same item's residuals correlate across every pair of occasions, as in R.
    for x in columns.values():
        for a, b in combinations(times, 2):
            lines.append(f"  {x}_t{a} WITH {x}_t{b};")
    if ordered and k < len(STEPS):
        lines += ["SAVEDATA:", f"  DIFFTEST = {step}.dif;"]
    lines += ["OUTPUT:", "  STDYX;", ""]
    return "\n".join(lines)


def estimator_lines(estimator: str) -> list[str]:
    if estimator == WLSMV:
        return ["  ESTIMATOR = WLSMV;", "  PARAMETERIZATION = THETA;"]
    return [f"  ESTIMATOR = {ESTIMATORS[estimator]};"]


def freed_lines(model: InvarianceModel, applied: bool) -> list[str]:
    if not model.freed:
        return []
    what = "Freed" if applied else "Not freed here, though labcatalog.yaml frees"
    return [f"! {what}: {f.item} {f.parameter}"[:WIDTH] for f in model.freed]


def run(mplus: str, folder: Path) -> list[Path]:
    outputs = []
    for path in sorted(folder.glob("*.inp")):
        out = path.with_suffix(".out")
        try:
            subprocess.run([mplus, path.name, out.name], cwd=folder, capture_output=True)
        except OSError:
            raise MplusError(
                f"Mplus not found at {mplus}; check the path on the Settings page"
            ) from None
        if not out.is_file():
            raise MplusError(f"Mplus wrote no output for {path.name}")
        outputs.append(out)
    return outputs
