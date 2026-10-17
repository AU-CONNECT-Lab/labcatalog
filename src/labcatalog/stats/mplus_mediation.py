import pandas as pd

from labcatalog.stats.analysis_script import Variable
from labcatalog.stats.cfa import ML, MLR, WLSMV
from labcatalog.stats.mediation import MediationModel
from labcatalog.stats.mplus import MISSING, WIDTH, data_text, statement, title_lines

INPUT = "mplus_mediation.inp"
DATA = "mplus_mediation.dat"


def mediation_files(model: MediationModel, frame: pd.DataFrame, title: str) -> dict[str, str]:
    latent = {r for r, v in roles(model).items() if model.items and v.items}
    columns = {}
    for role, v in roles(model).items():
        if role in latent:
            columns |= {f"{role}_{i}": c for i, c in enumerate(v.items, start=1)}
        else:
            columns[role] = v.column
    columns |= {f"cov{i}": v.column for i, v in enumerate(model.covariates, start=1)}
    # The people R fits too: everyone with all the model's values.
    data = frame[list(columns.values())].set_axis(list(columns), axis=1).dropna()
    at, centred = moderator_values(model, data, latent)
    for role in centred:
        data[role] = data[role] - data[role].mean()
    lines = [
        *title_lines(f"{title}, mediation"),
        *(f"! {n} = {c}"[:WIDTH] for n, c in columns.items()),
        *notes(model, latent),
        "DATA:",
        f'  FILE = "{DATA}";',
        "VARIABLE:",
        *statement(f"NAMES = {' '.join(columns)}"),
        *statement(f"USEVARIABLES = {' '.join([*columns, *products(model, latent)])}"),
        *categorical(model, latent),
        f"  MISSING = ALL ({MISSING});",
        *define(model, latent),
        "ANALYSIS:",
        *analysis_lines(model, latent),
        "MODEL:",
        *model_lines(model, latent),
        *constraint_lines(model, latent, at),
        "OUTPUT:",
        *output_lines(model, latent),
        "",
    ]
    return {INPUT: "\n".join(lines), DATA: data_text(data)}


def interacts(model: MediationModel, latent: set[str]) -> bool:
    # Mplus forms an interaction with a factor by XWITH, which needs numerical integration.
    return bool(model.moderators) and bool(latent)


def moderator_values(
    model: MediationModel, data: pd.DataFrame, latent: set[str]
) -> tuple[list[float], list[str]]:
    # The values of the centred moderator at which the conditional effects are taken.
    if not model.moderators:
        return [], []
    centred = ["w"] if interacts(model, latent) else ["x", "m", "w"]
    if "w" in latent:
        return [], []
    w = data["w"] - data["w"].mean()
    levels = sorted(w.unique())
    at = levels if len(levels) == 2 else [-w.std(), 0.0, w.std()]
    return [float(v) for v in at], centred


def notes(model: MediationModel, latent: set[str]) -> list[str]:
    found = ["! Labels: a, b, c are the paths X to M, M to Y and X to Y (direct)."]
    if "w" in latent:
        found.append(
            "! The factors have mean 0, so the effects are at W's mean and 1 SD either side."
        )
    elif model.moderators:
        centred = "X, M and W are" if not latent else "W is"
        found.append(f"! {centred} centred in the data, as in labcatalog's R code.")
    if model.bootstrap and model.estimator == MLR and not interacts(model, latent):
        found.append("! Mplus bootstraps with ML only; its estimates are the same as MLR's.")
    if model.bootstrap and interacts(model, latent):
        found.append("! Mplus does not bootstrap with numerical integration, so the intervals")
        found.append("! here are by the delta method, unlike labcatalog's bootstrap in modsem.")
    return found


def products(model: MediationModel, latent: set[str]) -> list[str]:
    if not model.moderators or interacts(model, latent):
        return []
    moderated = model.moderated
    return (["xw"] if moderated & {"a", "c"} else []) + (["mw"] if "b" in moderated else [])


def categorical(model: MediationModel, latent: set[str]) -> list[str]:
    if model.estimator != WLSMV:
        return []
    found = roles(model)
    names = [f"{r}_{i}" for r in ("x", "m", "y") for i in range(1, len(found[r].items) + 1)]
    return statement(f"CATEGORICAL = {' '.join(names)}")


def roles(model: MediationModel) -> dict[str, Variable]:
    found = {"x": model.x, "m": model.m, "y": model.y}
    if model.moderators:
        found["w"] = model.moderators[0].variable
    return found


def define(model: MediationModel, latent: set[str]) -> list[str]:
    made = products(model, latent)
    if not made:
        return []
    return ["DEFINE:", *(f"  {p} = {p[0]}*w;" for p in made)]


def analysis_lines(model: MediationModel, latent: set[str]) -> list[str]:
    if interacts(model, latent):
        return [
            f"  ESTIMATOR = {model.estimator.upper()};",
            "  TYPE = RANDOM;",
            "  ALGORITHM = INTEGRATION;",
        ]
    estimator = ML if model.bootstrap and model.estimator == MLR else model.estimator
    lines = [f"  ESTIMATOR = {estimator.upper()};"]
    if model.bootstrap:
        lines.append(f"  BOOTSTRAP = {model.bootstrap};")
    return lines


def model_lines(model: MediationModel, latent: set[str]) -> list[str]:
    def name(role: str) -> str:
        return role.upper() if role in latent else role

    lines = []
    for role, v in roles(model).items():
        if role in latent:
            lines += statement(f"{role.upper()} BY {role}_1-{role}_{len(v.items)}")
    x, m, y, w = (name(r) for r in ("x", "m", "y", "w"))
    moderated = model.moderated
    joined = interacts(model, latent)
    xw = "XW" if joined else "xw"
    mw = "MW" if joined else "mw"
    if joined:
        if moderated & {"a", "c"}:
            lines.append(f"  XW | {x} XWITH {w};")
        if "b" in moderated:
            lines.append(f"  MW | {m} XWITH {w};")
    covariates = [f"cov{i}" for i in range(1, len(model.covariates) + 1)]
    m_on = [(x, "a")] + ([(w, "a_w"), (xw, "a_xw")] if "a" in moderated else [])
    y_on = [(x, "c"), (m, "b")]
    if moderated & {"b", "c"}:
        y_on.append((w, "y_w"))
    if "b" in moderated:
        y_on.append((mw, "b_mw"))
    if "c" in moderated:
        y_on.append((xw, "c_xw"))
    for outcome, terms in ((m, m_on), (y, y_on)):
        lines += [f"  {outcome} ON {term} ({label});" for term, label in terms]
        if covariates:
            lines += statement(f"{outcome} ON {' '.join(covariates)}")
    if "w" in latent:
        lines.append(f"  {w} (v_w);")
    return lines


def constraint_lines(model: MediationModel, latent: set[str], at: list[float]) -> list[str]:
    moderated = model.moderated
    if not moderated:
        return [
            "MODEL CONSTRAINT:",
            "  NEW(indirect total);",
            "  indirect = a*b;",
            "  total = c + a*b;",
        ]
    # Values of W: its two answers or 1 SD either side of its mean; a factor's SD is estimated.
    values = [f"({v:.6g})" for v in at] or ["(-SQRT(v_w))", "0", "SQRT(v_w)"]
    definitions = []
    for k, v in enumerate(values, start=1):
        a = f"(a + a_xw*{v})" if "a" in moderated else "a"
        b = f"(b + b_mw*{v})" if "b" in moderated else "b"
        if moderated & {"a", "b"}:
            definitions.append((f"ind{k}", f"{a}*{b}"))
        if "c" in moderated:
            definitions.append((f"dir{k}", f"c + c_xw*{v}"))
    if not moderated & {"a", "b"}:
        definitions.insert(0, ("indirect", "a*b"))
    if moderated & {"a", "b"} == {"a"}:
        definitions.append(("index", "a_xw*b"))
    elif moderated & {"a", "b"} == {"b"}:
        definitions.append(("index", "a*b_mw"))
    return [
        "MODEL CONSTRAINT:",
        *statement(f"NEW({' '.join(n for n, _ in definitions)})"),
        *(f"  {n} = {e};" for n, e in definitions),
    ]


def output_lines(model: MediationModel, latent: set[str]) -> list[str]:
    if interacts(model, latent):
        return ["  CINTERVAL;"]
    interval = "  CINTERVAL(BOOTSTRAP);" if model.bootstrap else "  CINTERVAL;"
    return [interval, "  STDYX;"]
