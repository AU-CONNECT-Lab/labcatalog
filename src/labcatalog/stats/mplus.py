import subprocess
import textwrap
from pathlib import Path

from labcatalog.exceptions import MplusError
from labcatalog.stats.cfa import (
    SECOND_ORDER,
    SUBSCALE_SCORES,
    WLSMV,
    CfaModel,
    lavaan_names,
    model_estimator,
)

MISSING = -999
# Mplus reads at most 90 characters a line.
WIDTH = 80


def cfa_files(models: list[CfaModel], estimator: str, title: str) -> dict[str, str]:
    files = {}
    for n, model in enumerate(models, start=1):
        name = f"mplus_cfa_{n}"
        files[f"{name}.inp"] = cfa_input(model, f"{name}.dat", estimator, title)
        files[f"{name}.dat"] = data_text(model)
    return files


def data_text(model: CfaModel) -> str:
    # Free format without a header, as Mplus expects.
    return model.data.fillna(MISSING).to_csv(sep=" ", header=False, index=False, float_format="%g")


def cfa_input(model: CfaModel, data_file: str, estimator: str, title: str) -> str:
    items, factors = lavaan_names(model)
    names = f"x1-x{len(items)}"
    ordered = model_estimator(model, estimator) == WLSMV
    # A colon would read as the start of the next command.
    heading = f"{title}, {model.dataset}, {model.kind} model, written by labcatalog"
    lines = [
        "TITLE:",
        *textwrap.wrap(
            heading.replace(":", ","), WIDTH, initial_indent="  ", subsequent_indent="  "
        ),
        *comment_lines(items, model.kind == SUBSCALE_SCORES),
        "DATA:",
        f'  FILE = "{data_file}";',
        "VARIABLE:",
        f"  NAMES = {names};",
        *([f"  CATEGORICAL = {names};"] if ordered else []),
        f"  MISSING = ALL ({MISSING});",
        "ANALYSIS:",
        f"  ESTIMATOR = {'WLSMV' if ordered else 'ML'};",
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
    lines += ["OUTPUT:", "  STDYX;", ""]
    return "\n".join(lines)


def comment_lines(items: dict[str, str], scores: bool) -> list[str]:
    what = "Subscale scores" if scores else "Items, with reverse-scored items already reversed"
    return [f"! {what}:", *(f"! {name} = {column}"[:WIDTH] for column, name in items.items())]


def statement(text: str) -> list[str]:
    return textwrap.wrap(f"{text};", WIDTH, initial_indent="  ", subsequent_indent="    ")


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
