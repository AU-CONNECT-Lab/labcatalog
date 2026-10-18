from dataclasses import dataclass, field
from html import escape

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common, preferences
from labcatalog.gui.common import col, computed, fmt, note, p_value, panel
from labcatalog.gui.paper import paper_table, result_actions, results_text
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats import mediation as med
from labcatalog.stats.cfa import ESTIMATORS
from labcatalog.stats.mediation_r import mediation_code
from labcatalog.stats.mplus_mediation import mediation_files

NO_MODERATOR = ""
PATH_NAMES = {"a": "a (X → M)", "b": "b (M → Y)", "c": "c′ (X → Y)"}


@dataclass
class Choices:
    x: str | None = None
    m: str | None = None
    y: str | None = None
    covariates: list[str] = field(default_factory=list)
    # W1 and W2, each with the paths it moderates; W2 is offered once W1 is chosen.
    moderators: list[str] = field(default_factory=lambda: [NO_MODERATOR] * med.MAX_MODERATORS)
    paths: list[list[str]] = field(
        default_factory=lambda: [["a"] for _ in range(med.MAX_MODERATORS)]
    )
    estimator: str = med.ML
    booted: bool = True
    bootstrap: int = med.DEFAULT_BOOTSTRAP
    items: bool = False
    fiml: bool = True


def render(
    result: CatalogResult,
    sample: analysis.Sample,
    chosen: Choices,
    choices: dict[str, str],
    totals: list[str],
) -> None:
    scores = {k: v for k, v in choices.items() if not k.startswith(analysis.ITEM_PREFIX)}

    def settle() -> None:
        # Total scores first, so that X, M and Y start on different instruments.
        offered = scores if chosen.items else choices
        keys = list(dict.fromkeys([*[t for t in totals if t in offered], *offered]))
        taken: list[str] = []
        for name in ("x", "m", "y"):
            value = getattr(chosen, name)
            if value not in offered or value in taken:
                value = next((k for k in keys if k not in taken), keys[0])
                setattr(chosen, name, value)
            taken.append(value)
        chosen.covariates = [c for c in chosen.covariates if c in choices]
        # A W2 left on its own moves up to W1, with its paths.
        kept = [
            (w, p) for w, p in zip(chosen.moderators, chosen.paths, strict=True) if w in choices
        ]
        kept += [(NO_MODERATOR, ["a"])] * (med.MAX_MODERATORS - len(kept))
        chosen.moderators = [w for w, _ in kept]
        chosen.paths = [list(p) for _, p in kept]
        if chosen.estimator not in estimators(chosen):
            chosen.estimator = med.ML

    def variable(data: script.AnalysisData, key: str) -> script.Variable:
        # In Items mode a score brings its items, to be the indicators of its factor.
        if chosen.items and not key.startswith(analysis.ITEM_PREFIX):
            return data.score(key, items=True)
        return data.variable(key)

    def by_study(data: script.AnalysisData) -> list[script.Variable]:
        # Pooled studies enter M and Y as fixed effects, as in the pooled regressions.
        return data.study_dummies() if analysis.pooling(result, sample.datasets) else []

    def model_of(data: script.AnalysisData) -> med.MediationModel:
        moderators = [
            med.Moderator(variable(data, w), tuple(paths))
            for w, paths in zip(chosen.moderators, chosen.paths, strict=True)
            if w and paths
        ]
        return med.MediationModel(
            variable(data, chosen.x),
            variable(data, chosen.m),
            variable(data, chosen.y),
            [data.variable(c) for c in chosen.covariates] + by_study(data),
            moderators,
            chosen.estimator,
            chosen.bootstrap if chosen.booted else 0,
            chosen.items,
            chosen.fiml,
        )

    async def run() -> None:
        rscript = preferences.load().get(preferences.RSCRIPT)
        body.clear()
        if not rscript:
            with body:
                note("Set the path to Rscript on the Settings page; mediation runs in R only.")
            return
        used = [chosen.x, chosen.m, chosen.y, *chosen.moderators, *chosen.covariates]
        used = [k for k in used if k]
        if len(set(used)) < len(used):
            with body:
                note("X, M, Y, the moderators and the covariates must all be different variables.")
            return
        data = script.AnalysisData(result, sample)
        model = model_of(data)
        if problem := item_problem(model):
            with body:
                note(problem)
            return
        frame = data.frame()
        code = mediation_code(model, workers())
        with body:
            ui.spinner()
            note(running_text(model))
        try:
            found, _ = await computed(script.run_code, result, sample, frame, code, rscript)
        except LabCatalogError as err:
            body.clear()
            with body:
                note(str(err))
            return
        if body.is_deleted:
            return
        fit = med.read_fit(found, model)
        r_text, _ = script.script(result, sample, [code])
        texts = {script.DATA_FILE: frame.to_csv(index=False), "mediation.R": r_text}
        texts |= mediation_files(model, frame, f"{model.x.label} on {model.y.label}")
        body.clear()
        with body:
            show(model, fit, texts)

    def show(model: med.MediationModel, fit: med.MediationFit, texts: dict[str, str]) -> None:
        ui.html(diagram(model, fit), sanitize=False).classes("w-full")
        shown = PaperTable(
            f"Mediation of {model.x.label} on {model.y.label} Through {model.m.label}",
            *effects_table(model, fit),
            table_note(model, fit),
        )
        paper_table(shown)
        results_text(results.mediation_text(model, fit, common.decimals), [shown])
        result_actions(
            result, "mediation", {"mediation": shown}, texts=texts, engine="Computed in R."
        )
        with ui.expansion("Code", icon="code").props("dense").classes("w-full"):
            note(f"Runs in a folder that holds {script.DATA_FILE}; Save to outputs writes both.")
            ui.code(texts["mediation.R"], language="r").classes("w-full")

    def choose(name: str, value) -> None:
        setattr(chosen, name, value)
        settle()
        controls.refresh()
        body.clear()
        with body:
            preview()

    def set_moderator(k: int, value: str | None) -> None:
        chosen.moderators[k] = value or NO_MODERATOR
        choose("moderators", chosen.moderators)

    def set_path(k: int, path: str, on: bool) -> None:
        kept = set(chosen.paths[k]) - {path} | ({path} if on else set())
        chosen.paths[k] = [p for p in med.PATHS if p in kept]
        choose("paths", chosen.paths)

    def preview() -> None:
        data = script.AnalysisData(result, sample)
        model = model_of(data)
        ui.html(diagram(model, None), sanitize=False).classes("w-full")
        if model.fiml and not model.full_information:
            which = "WLSMV" if model.estimator == med.WLSMV else "QML, for an observed moderator,"
            note(f"{which} has no FIML, so the model keeps everyone with all its values.")

    @ui.refreshable
    def controls() -> None:
        offered = scores if chosen.items else choices
        with ui.row().classes("w-full items-center gap-4"):
            ui.toggle(
                {False: "Scores", True: "Items"},
                value=chosen.items,
                on_change=lambda e: choose("items", e.value),
            ).props("dense no-caps").tooltip(
                "Scores as observed variables, or each score's items as indicators of its factor"
            )
            for name in ("x", "m", "y"):
                ui.select(
                    offered,
                    value=getattr(chosen, name),
                    label=name.upper(),
                    with_input=True,
                    on_change=lambda e, name=name: choose(name, e.value),
                ).props("dense outlined").classes("w-64")
            ui.select(
                choices,
                multiple=True,
                value=chosen.covariates,
                label="Covariates",
                with_input=True,
                on_change=lambda e: choose("covariates", e.value or []),
            ).props("dense outlined use-chips").classes("min-w-64 grow")
        # W2 is offered once W1 is chosen; with one moderator it is plain W.
        shown = 1 + bool(chosen.moderators[0])
        for k in range(min(shown, med.MAX_MODERATORS)):
            letter = f"W{k + 1}" if chosen.moderators[1] or k else "W"
            with ui.row().classes("w-full items-center gap-4"):
                ui.select(
                    {NO_MODERATOR: "No moderator", **choices},
                    value=chosen.moderators[k],
                    label=f"Moderator {letter}",
                    with_input=True,
                    on_change=lambda e, k=k: set_moderator(k, e.value),
                ).props("dense outlined").classes("w-64")
                if chosen.moderators[k]:
                    for path, label in PATH_NAMES.items():
                        ui.checkbox(
                            label,
                            value=path in chosen.paths[k],
                            on_change=lambda e, k=k, path=path: set_path(k, path, e.value),
                        ).props("dense")
        with ui.row().classes("w-full items-center gap-4"):
            ui.space()
            ui.toggle(
                {e: ESTIMATORS[e] for e in estimators(chosen)},
                value=chosen.estimator,
                on_change=lambda e: choose("estimator", e.value),
            ).props("dense no-caps")
            ui.toggle(
                {True: "FIML", False: "Complete cases"},
                value=chosen.fiml,
                on_change=lambda e: choose("fiml", e.value),
            ).props("dense no-caps").tooltip(
                "Missing values: everyone with any of the model's values by full-information "
                "maximum likelihood, or only those with all of them"
            )
            ui.toggle(
                {True: "Bootstrap", False: "None"},
                value=chosen.booted,
                on_change=lambda e: choose("booted", e.value),
            ).props("dense no-caps").tooltip(
                "Percentile bootstrap intervals, or Wald intervals without resampling"
            )
            # Kept in place when off, so the controls after it do not move.
            ui.number(
                "Bootstrap resamples",
                value=chosen.bootstrap,
                min=100,
                step=100,
                format="%d",
                on_change=lambda e: setattr(
                    chosen, "bootstrap", int(e.value or 0) or med.DEFAULT_BOOTSTRAP
                ),
            ).props("dense outlined").classes("w-44").set_enabled(chosen.booted)
            ui.button("Fit", icon="play_arrow", on_click=run).props("no-caps")
        if chosen.items and moderated(chosen):
            note(
                "Latent interactions (modsem) treat the items as continuous, so WLSMV is not "
                "offered; with Bootstrap, each resample refits the model, which takes minutes."
            )

    settle()
    with panel("Mediation", "X on Y through a mediator M, with an optional moderator W"):
        controls()
        body = ui.column().classes("w-full gap-2")
        with body:
            preview()


def moderated(chosen: Choices) -> bool:
    return any(w and paths for w, paths in zip(chosen.moderators, chosen.paths, strict=True))


def letters(model: med.MediationModel) -> list[str]:
    return [f"W{s}" for s in model.tags]


def estimators(chosen: Choices) -> tuple[str, ...]:
    if not chosen.items:
        return med.SCORE_ESTIMATORS
    return med.MODERATED_ITEM_ESTIMATORS if moderated(chosen) else med.ITEM_ESTIMATORS


def item_problem(model: med.MediationModel) -> str | None:
    # Factors need items of their own.
    if not model.items:
        return None
    roles = {"X": model.x, "M": model.m, "Y": model.y}
    if missing := [r for r, v in roles.items() if not v.items]:
        return f"In Items mode, {' and '.join(missing)} need a score with two or more items."
    for letter, moderator in zip(letters(model), model.moderators, strict=True):
        if moderator.variable.items:
            roles[letter] = moderator.variable
    seen: dict[str, str] = {}
    for role, v in roles.items():
        for item in v.items:
            if item in seen:
                return (
                    f"{seen[item]} and {role} share items, such as {item}; a factor needs items "
                    "of its own, so pick scores that do not overlap, such as two subscales."
                )
            seen[item] = role
    return None


def running_text(model: med.MediationModel) -> str:
    if not model.bootstrap:
        return "Fitting in R."
    if model.package == med.MODSEM:
        return f"Fitting in R with {model.bootstrap} bootstrap resamples; this takes minutes."
    return f"Fitting in R with {model.bootstrap} bootstrap resamples."


def workers() -> int:
    return int(preferences.load().get(preferences.BOOTSTRAP_WORKERS, med.DEFAULT_WORKERS))


def effects_table(
    model: med.MediationModel, fit: med.MediationFit
) -> tuple[list[dict], list[dict]]:
    columns = [
        col("effect", "Effect"),
        col("b", "b", numeric=True),
        col("se", "SE", numeric=True),
        col("p", "p", numeric=True),
        col("ci", "95% CI", numeric=True),
        col("beta", "β", numeric=True),
    ]
    rows = [
        {
            "effect": label,
            "b": fmt(e.estimate),
            "se": fmt(e.se),
            "p": p_value(e.p),
            "ci": f"[{fmt(e.low)}, {fmt(e.high)}]" if e.low is not None else "",
            "beta": fmt(e.standardized),
        }
        for key, label in row_names(model, fit).items()
        if (e := fit.effects.get(key)) is not None
    ]
    return columns, rows


def row_names(model: med.MediationModel, fit: med.MediationFit) -> dict[str, str]:
    # Rows of the effects table, in order, with what each is.
    named = list(zip(model.tags, letters(model), strict=True))
    names = {"a": "a: X → M"}
    for s, w in named:
        names |= {f"a_w{s}": f"{w} → M", f"a_xw{s}": f"X × {w} → M"}
    names |= {"b": "b: M → Y", "c": "c′: X → Y (direct)"}
    if "c" in model.moderated:
        means = "the mean of W" if len(named) == 1 else "the means of W1 and W2"
        names["c"] = f"c′: X → Y at {means}"
    names |= {f"y_w{s}": f"{w} → Y" for s, w in named}
    names |= {f"b_mw{s}": f"M × {w} → Y" for s, w in named}
    names |= {f"c_xw{s}": f"X × {w} → Y" for s, w in named}
    names |= {"indirect": "a × b: indirect", "total": "c: total"}
    places = [
        med.at_labels(m.variable, values)
        for m, values in zip(model.moderators, fit.at, strict=True)
    ]
    for kind in ("indirect", "direct"):
        for label, spots in med.conditions(model, fit, kind):
            where = ", ".join(f"{named[k][1]} = {places[k][i - 1]}" for k, i in spots)
            names[label] = f"{kind.capitalize()} at {where}"
    for k in med.indexed(model):
        names[med.index_label(model, k)] = (
            "Index of moderated mediation"
            if len(named) == 1
            else f"Index of partial moderated mediation by {named[k][1]}"
        )
    return names


def table_note(model: med.MediationModel, fit: med.MediationFit) -> str:
    roles = {"X": model.x, "M": model.m, "Y": model.y}
    roles |= {w: m.variable for w, m in zip(letters(model), model.moderators, strict=True)}
    ws = results.series(letters(model))
    legend = "; ".join(f"{k} = {v.label}" for k, v in roles.items())
    covariates = (
        f" Covariates on M and Y: {', '.join(v.label for v in model.covariates)}."
        if model.covariates
        else ""
    )
    factors = [r for r, v in roles.items() if model.items and v.items]
    centred = ""
    if model.moderators:
        verb, mean = ("is", "its mean") if len(model.moderators) == 1 else ("are", "their means")
        centred = (
            f" The factors have mean 0 and {ws} {verb} centred at {mean}."
            if model.items
            else f" {', '.join(['X', 'M', *letters(model)[:-1]])} and {letters(model)[-1]} are "
            "centred at their means."
        )
    if factors:
        centred = (
            f" {results.series(factors)} are factors of their items, each item's loading on the first "
            f"fixed at 1.{centred}"
        )
    beta = (
        f" β is fully standardized; effects at values of {ws} have none."
        if model.moderators
        else " β is fully standardized."
    )
    if fit.package == med.MODSEM:
        fitted = " A latent interaction model has no chi-square test of fit."
    elif fit.fit.get("df"):
        values = fit.fit
        fitted = (
            f" Model fit: χ²({values['df']:g}) = {fmt(values['chisq'])}, "
            f"{results.p_text(values['pvalue'])}, CFI = {fmt(values['cfi'])}, RMSEA = "
            f"{fmt(values['rmsea'])}, SRMR = {fmt(values['srmr'])}."
        )
    else:
        fitted = " The model is saturated (df = 0), so it has no fit test."
    return (
        f"{legend}. Unstandardized estimates; {fit.package}, {med.method_text(fit)}; N = {fit.n}; "
        f"95% {med.intervals_text(fit)}.{beta}{centred}{covariates}{fitted}"
    )


# Box centres and size of the conceptual diagram, in its own units.
BOX_W, BOX_H = 200, 52
SPOTS = {
    "x": (130, 230),
    "m": (450, 70),
    "y": (770, 230),
    "w": (450, 330),
    "w1": (300, 330),
    "w2": (600, 330),
}


def diagram(model: med.MediationModel, fit: med.MediationFit | None) -> str:
    # X, M and Y as a triangle, each W below, with its arrows ending on the paths it moderates.
    labels = {"x": model.x.label, "m": model.m.label, "y": model.y.label}
    labels |= {f"w{s}": m.variable.label for s, m in zip(model.tags, model.moderators, strict=True)}
    e = fit.effects if fit is not None else {}

    def value(key: str, symbol: str) -> str:
        return f"{symbol} = {fmt(e[key].estimate)}" if key in e else symbol

    paths = {
        "a": ("x", "m", value("a", "a")),
        "b": ("m", "y", value("b", "b")),
        "c": ("x", "y", value("c", "c′")),
    }
    parts = []
    for key, (start, end, text) in paths.items():
        (x1, y1), (x2, y2) = edge(start, end)
        parts.append(arrow(x1, y1, x2, y2))
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dy = -14 if key != "c" else 22
        parts.append(text_at(mx + (-34 if key == "a" else 34 if key == "b" else 0), my + dy, text))
    for s, moderator in zip(model.tags, model.moderators, strict=True):
        wx, wy = SPOTS[f"w{s}"]
        for key in moderator.paths:
            (x1, y1), (x2, y2) = edge(paths[key][0], paths[key][1])
            parts.append(arrow(wx, wy - BOX_H / 2, (x1 + x2) / 2, (y1 + y2) / 2, dashed=True))
    roles = {"x": model.x, "m": model.m, "y": model.y}
    roles |= {f"w{s}": m.variable for s, m in zip(model.tags, model.moderators, strict=True)}
    for name, text in labels.items():
        cx, cy = SPOTS[name]
        # Factors are ellipses and observed variables boxes, as in path diagrams.
        if model.items and roles[name].items:
            parts.append(
                f'<ellipse cx="{cx}" cy="{cy}" rx="{BOX_W / 2}" ry="{BOX_H / 2 + 4}" '
                'fill="var(--lc-surface)" stroke="var(--lc-ink)" stroke-width="1.2"/>'
            )
        else:
            parts.append(
                f'<rect x="{cx - BOX_W / 2}" y="{cy - BOX_H / 2}" width="{BOX_W}" '
                f'height="{BOX_H}" rx="6" fill="var(--lc-surface)" stroke="var(--lc-ink)" '
                'stroke-width="1.2"/>'
            )
        short = text if len(text) <= 26 else text[:25] + "…"
        parts.append(
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="14" '
            f'fill="var(--lc-ink)"><tspan font-weight="600">{name.upper()}</tspan> '
            f"{escape(short)}<title>{escape(text)}</title></text>"
        )
    height = 380 if model.moderators else 280
    return (
        f'<svg viewBox="0 0 900 {height}" style="max-height: {height}px; width: 100%" '
        'role="img" aria-label="Conceptual diagram of the mediation model">'
        '<defs><marker id="lc-head" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
        'fill="var(--lc-ink)"/></marker></defs>' + "".join(parts) + "</svg>"
    )


def edge(start: str, end: str) -> tuple[tuple[float, float], tuple[float, float]]:
    # From the side of one box to the side of the other.
    (x1, y1), (x2, y2) = SPOTS[start], SPOTS[end]
    if y1 == y2:
        return (x1 + BOX_W / 2, y1), (x2 - BOX_W / 2, y2)
    down = y2 > y1
    return (x1 + BOX_W / 4 * (1 if x2 > x1 else -1), y1 + (BOX_H / 2 if down else -BOX_H / 2)), (
        x2 - BOX_W / 4 * (1 if x2 > x1 else -1),
        y2 - (BOX_H / 2 if down else -BOX_H / 2),
    )


def arrow(x1: float, y1: float, x2: float, y2: float, dashed: bool = False) -> str:
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="var(--lc-ink)" '
        f'stroke-width="1.4" marker-end="url(#lc-head)"{dash}/>'
    )


def text_at(x: float, y: float, text: str) -> str:
    return (
        f'<text x="{x}" y="{y}" text-anchor="middle" font-size="14" '
        f'fill="var(--lc-muted)">{escape(text)}</text>'
    )
