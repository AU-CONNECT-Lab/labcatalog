from itertools import product

import pandas as pd

from labcatalog.stats.analysis_script import Variable
from labcatalog.stats.cfa import ML, MLR, WLSMV
from labcatalog.stats.mediation import MediationModel, depends, indexed
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
) -> tuple[list[list[float]], list[str]]:
    # Each moderator's centred values at which the conditional effects are taken; a factor's
    # values come from its estimated variance instead.
    ws = [f"w{s}" for s in model.tags]
    if not ws:
        return [], []
    centred = [w for w in ws if w not in latent] if interacts(model, latent) else ["x", "m", *ws]
    at = []
    for w in ws:
        if w in latent:
            at.append([])
            continue
        values = data[w] - data[w].mean()
        levels = sorted(values.unique())
        found = levels if len(levels) == 2 else [-values.std(), 0.0, values.std()]
        at.append([float(v) for v in found])
    return at, centred


def notes(model: MediationModel, latent: set[str]) -> list[str]:
    found = ["! Labels: a, b, c are the paths X to M, M to Y and X to Y (direct)."]
    ws = [f"w{s}" for s in model.tags]
    named = " and ".join(w.upper() for w in ws)
    if ws and all(w in latent for w in ws):
        found.append(
            f"! The factors have mean 0, so the effects are at {named}'s mean and 1 SD either side."
        )
    elif ws:
        observed = [w.upper() for w in ws if w not in latent]
        centred = (
            f"{' and '.join(observed)} {'is' if len(observed) == 1 else 'are'}"
            if latent
            else f"X, M and {' and '.join(observed)} are"
        )
        found.append(f"! {centred} centred in the data, as in labcatalog's R code.")
    if len(ws) == 2:
        found.append("! in12 is the indirect effect at W1's 1st value and W2's 2nd; in1_2 at W1's")
        found.append("! 2nd value alone; di likewise for the direct effect; index1 is W1's index.")
    if model.bootstrap and model.estimator == MLR and not interacts(model, latent):
        found.append("! Mplus bootstraps with ML only; its estimates are the same as MLR's.")
    if model.bootstrap and interacts(model, latent):
        found.append("! Mplus does not bootstrap with numerical integration, so the intervals")
        found.append("! here are by the delta method, unlike labcatalog's bootstrap in modsem.")
    return found


def products(model: MediationModel, latent: set[str]) -> list[str]:
    if not model.moderators or interacts(model, latent):
        return []
    found = []
    for s, moderator in zip(model.tags, model.moderators, strict=True):
        paths = set(moderator.paths)
        found += ([f"xw{s}"] if paths & {"a", "c"} else []) + ([f"mw{s}"] if "b" in paths else [])
    return found


def categorical(model: MediationModel, latent: set[str]) -> list[str]:
    if model.estimator != WLSMV:
        return []
    found = roles(model)
    names = [f"{r}_{i}" for r in ("x", "m", "y") for i in range(1, len(found[r].items) + 1)]
    return statement(f"CATEGORICAL = {' '.join(names)}")


def roles(model: MediationModel) -> dict[str, Variable]:
    found = {"x": model.x, "m": model.m, "y": model.y}
    found |= {f"w{s}": m.variable for s, m in zip(model.tags, model.moderators, strict=True)}
    return found


def define(model: MediationModel, latent: set[str]) -> list[str]:
    made = products(model, latent)
    if not made:
        return []
    # xw1 is x times w1.
    return ["DEFINE:", *(f"  {p} = {p[0]}*{p[1:]};" for p in made)]


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
    x, m, y = (name(r) for r in ("x", "m", "y"))
    joined = interacts(model, latent)
    m_on, y_on = [(x, "a")], [(x, "c"), (m, "b")]
    for s, moderator in zip(model.tags, model.moderators, strict=True):
        w, paths = name(f"w{s}"), set(moderator.paths)
        xw = f"XW{s}" if joined else f"xw{s}"
        mw = f"MW{s}" if joined else f"mw{s}"
        if joined and paths & {"a", "c"}:
            lines.append(f"  {xw} | {x} XWITH {w};")
        if joined and "b" in paths:
            lines.append(f"  {mw} | {m} XWITH {w};")
        if "a" in paths:
            m_on += [(w, f"a_w{s}"), (xw, f"a_xw{s}")]
        if paths & {"b", "c"}:
            y_on.append((w, f"y_w{s}"))
        if "b" in paths:
            y_on.append((mw, f"b_mw{s}"))
        if "c" in paths:
            y_on.append((xw, f"c_xw{s}"))
    covariates = [f"cov{i}" for i in range(1, len(model.covariates) + 1)]
    for outcome, terms in ((m, m_on), (y, y_on)):
        lines += [f"  {outcome} ON {term} ({label});" for term, label in terms]
        if covariates:
            lines += statement(f"{outcome} ON {' '.join(covariates)}")
    for s in model.tags:
        if f"w{s}" in latent:
            lines.append(f"  W{s} (v_w{s});")
    return lines


def constraint_lines(model: MediationModel, latent: set[str], at: list[list[float]]) -> list[str]:
    if not model.moderated:
        return [
            "MODEL CONSTRAINT:",
            "  NEW(indirect total);",
            "  indirect = a*b;",
            "  total = c + a*b;",
        ]
    tags = model.tags
    # Values of each W: its two answers or 1 SD either side of its mean; a factor's SD is estimated.
    values = [
        [f"({v:.6g})" for v in found] or [f"(-SQRT(v_w{s}))", "0", f"SQRT(v_w{s})"]
        for s, found in zip(tags, at, strict=True)
    ]
    single = len(model.moderators) == 1
    definitions = []
    for kind, short in (("indirect", "in"), ("direct", "di")):
        which = depends(model, kind)
        if not which:
            if kind == "indirect":
                definitions.append(("indirect", "a*b"))
            continue
        for places in product(*(range(len(values[k])) for k in which)):
            chosen = dict(zip(which, places, strict=True))

            def path(symbol: str, term: str, on: list[int], chosen=chosen) -> str:
                terms = [f"{term}{tags[k]}*{values[k][chosen[k]]}" for k in on if k in chosen]
                return f"({symbol} + {' + '.join(terms)})" if terms else symbol

            spots = "".join(str(i + 1) for i in places)
            if single:
                label = f"{'ind' if kind == 'indirect' else 'dir'}{spots}"
            elif len(which) == 1:
                label = f"{short}{which[0] + 1}_{spots}"
            else:
                label = f"{short}{spots}"
            if kind == "indirect":
                effect = f"{path('a', 'a_xw', model.on('a'))}*{path('b', 'b_mw', model.on('b'))}"
            else:
                effect = path("c", "c_xw", model.on("c"))[1:-1]
            definitions.append((label, effect))
    for k in indexed(model):
        product_ = f"a_xw{tags[k]}*b" if k in model.on("a") else f"a*b_mw{tags[k]}"
        definitions.append(("index" if single else f"index{k + 1}", product_))
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
