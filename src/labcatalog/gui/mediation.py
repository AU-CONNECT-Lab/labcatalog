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

NO_MODERATOR = ""
PATH_NAMES = {"a": "a (X → M)", "b": "b (M → Y)", "c": "c′ (X → Y)"}
# Rows of the effects table, in order, with what each is.
ROWS = {
    "a": "a: X → M",
    "a_w": "W → M",
    "a_xw": "X × W → M",
    "b": "b: M → Y",
    "c": "c′: X → Y (direct)",
    "y_w": "W → Y",
    "b_mw": "M × W → Y",
    "c_xw": "X × W → Y",
    "indirect": "a × b: indirect",
    "total": "c: total",
}


@dataclass
class Choices:
    x: str | None = None
    m: str | None = None
    y: str | None = None
    covariates: list[str] = field(default_factory=list)
    moderator: str = NO_MODERATOR
    paths: list[str] = field(default_factory=lambda: ["a"])
    estimator: str = med.ML
    booted: bool = True
    bootstrap: int = med.DEFAULT_BOOTSTRAP


def render(
    result: CatalogResult,
    sample: analysis.Sample,
    chosen: Choices,
    choices: dict[str, str],
    totals: list[str],
) -> None:
    # Total scores first, so that X, M and Y start on different instruments.
    keys = list(dict.fromkeys([*totals, *choices]))
    taken: list[str] = []
    for name in ("x", "m", "y"):
        value = getattr(chosen, name)
        if value not in choices or value in taken:
            value = next((k for k in keys if k not in taken), keys[0])
            setattr(chosen, name, value)
        taken.append(value)
    chosen.covariates = [c for c in chosen.covariates if c in choices]
    if chosen.moderator not in choices:
        chosen.moderator = NO_MODERATOR

    def model_of(data: script.AnalysisData) -> med.MediationModel:
        moderators = (
            [med.Moderator(data.variable(chosen.moderator), tuple(chosen.paths))]
            if chosen.moderator and chosen.paths
            else []
        )
        return med.MediationModel(
            data.variable(chosen.x),
            data.variable(chosen.m),
            data.variable(chosen.y),
            [data.variable(c) for c in chosen.covariates],
            moderators,
            chosen.estimator,
            chosen.bootstrap if chosen.booted else 0,
        )

    async def run() -> None:
        rscript = preferences.load().get(preferences.RSCRIPT)
        body.clear()
        if not rscript:
            with body:
                note("Set the path to Rscript on the Settings page; mediation runs in R only.")
            return
        used = [chosen.x, chosen.m, chosen.y, chosen.moderator, *chosen.covariates]
        used = [k for k in used if k]
        if len(set(used)) < len(used):
            with body:
                note("X, M, Y, the moderator and the covariates must all be different variables.")
            return
        data = script.AnalysisData(result, sample)
        model = model_of(data)
        frame = data.frame()
        code = med.mediation_code(model, workers())
        with body:
            ui.spinner()
            note(
                f"Fitting in R with {chosen.bootstrap} bootstrap resamples."
                if chosen.booted
                else "Fitting in R."
            )
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
        moderator_row.refresh()
        body.clear()
        with body:
            preview()

    def set_path(path: str, on: bool) -> None:
        kept = set(chosen.paths) - {path} | ({path} if on else set())
        choose("paths", [p for p in med.PATHS if p in kept])

    def preview() -> None:
        data = script.AnalysisData(result, sample)
        ui.html(diagram(model_of(data), None), sanitize=False).classes("w-full")

    with panel("Mediation", "X on Y through a mediator M, with an optional moderator W"):
        with ui.row().classes("w-full items-center gap-4"):
            for name in ("x", "m", "y"):
                ui.select(
                    choices,
                    value=getattr(chosen, name),
                    label=name.upper(),
                    with_input=True,
                    on_change=lambda e, name=name: choose(name, e.value),
                ).props("dense outlined").classes("w-72")
            ui.select(
                choices,
                multiple=True,
                value=chosen.covariates,
                label="Covariates",
                with_input=True,
                on_change=lambda e: choose("covariates", e.value or []),
            ).props("dense outlined use-chips").classes("min-w-72 grow")

        @ui.refreshable
        def moderator_row() -> None:
            with ui.row().classes("w-full items-center gap-4"):
                ui.select(
                    {NO_MODERATOR: "No moderator", **choices},
                    value=chosen.moderator,
                    label="Moderator W",
                    with_input=True,
                    on_change=lambda e: choose("moderator", e.value or NO_MODERATOR),
                ).props("dense outlined").classes("w-72")
                if chosen.moderator:
                    for path, label in PATH_NAMES.items():
                        ui.checkbox(
                            label,
                            value=path in chosen.paths,
                            on_change=lambda e, path=path: set_path(path, e.value),
                        ).props("dense")
                ui.space()
                ui.toggle(
                    {e: ESTIMATORS[e] for e in med.SCORE_ESTIMATORS},
                    value=chosen.estimator,
                    on_change=lambda e: choose("estimator", e.value),
                ).props("dense no-caps")
                ui.toggle(
                    {True: "Bootstrap", False: "None"},
                    value=chosen.booted,
                    on_change=lambda e: choose("booted", e.value),
                ).props("dense no-caps").tooltip(
                    "Percentile bootstrap intervals, or Wald intervals without resampling"
                )
                if chosen.booted:
                    ui.number(
                        "Bootstrap resamples",
                        value=chosen.bootstrap,
                        min=100,
                        step=100,
                        format="%d",
                        on_change=lambda e: setattr(
                            chosen, "bootstrap", int(e.value or 0) or med.DEFAULT_BOOTSTRAP
                        ),
                    ).props("dense outlined").classes("w-44")
                ui.button("Fit", icon="play_arrow", on_click=run).props("no-caps")

        moderator_row()
        body = ui.column().classes("w-full gap-2")
        with body:
            preview()


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
    ]
    places = med.at_labels(model, fit)
    names = dict(ROWS)
    if "c" in model.moderated:
        names["c"] = "c′: X → Y at the mean of W"
    for k, place in enumerate(places, start=1):
        names[f"indirect_{k}"] = f"Indirect at W = {place}"
    for k, place in enumerate(places, start=1):
        names[f"direct_{k}"] = f"Direct at W = {place}"
    names["index"] = "Index of moderated mediation"
    rows = [
        {
            "effect": label,
            "b": fmt(e.estimate),
            "se": fmt(e.se),
            "p": p_value(e.p),
            "ci": f"[{fmt(e.low)}, {fmt(e.high)}]" if e.low is not None else "",
        }
        for key, label in names.items()
        if (e := fit.effects.get(key)) is not None
    ]
    return columns, rows


def table_note(model: med.MediationModel, fit: med.MediationFit) -> str:
    roles = {"X": model.x, "M": model.m, "Y": model.y}
    if model.moderators:
        roles["W"] = model.moderators[0].variable
    legend = "; ".join(f"{k} = {v.label}" for k, v in roles.items())
    covariates = (
        f" Covariates on M and Y: {', '.join(v.label for v in model.covariates)}."
        if model.covariates
        else ""
    )
    centred = " X, M and W are centred at their means." if model.moderators else ""
    if fit.fit.get("df"):
        values = fit.fit
        fitted = (
            f" Model fit: χ²({values['df']:g}) = {fmt(values['chisq'])}, p = "
            f"{p_value(values['pvalue'])}, CFI = {fmt(values['cfi'])}, RMSEA = "
            f"{fmt(values['rmsea'])}, SRMR = {fmt(values['srmr'])}."
        )
    else:
        fitted = " The model is saturated (df = 0), so it has no fit test."
    return (
        f"{legend}. Unstandardized estimates; lavaan, {med.method_text(fit)}; N = {fit.n}; 95% "
        f"{med.intervals_text(fit)}.{centred}{covariates}{fitted}"
    )


# Box centres and size of the conceptual diagram, in its own units.
BOX_W, BOX_H = 200, 52
SPOTS = {"x": (130, 230), "m": (450, 70), "y": (770, 230), "w": (450, 330)}


def diagram(model: med.MediationModel, fit: med.MediationFit | None) -> str:
    # X, M and Y as a triangle, W below, with W's arrows ending on the paths it moderates.
    labels = {"x": model.x.label, "m": model.m.label, "y": model.y.label}
    if model.moderators:
        labels["w"] = model.moderators[0].variable.label
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
    if "w" in labels:
        wx, wy = SPOTS["w"]
        for key in model.moderated:
            (x1, y1), (x2, y2) = edge(paths[key][0], paths[key][1])
            parts.append(arrow(wx, wy - BOX_H / 2, (x1 + x2) / 2, (y1 + y2) / 2, dashed=True))
    for name, text in labels.items():
        cx, cy = SPOTS[name]
        parts.append(
            f'<rect x="{cx - BOX_W / 2}" y="{cy - BOX_H / 2}" width="{BOX_W}" height="{BOX_H}" '
            'rx="6" fill="var(--lc-surface)" stroke="var(--lc-ink)" stroke-width="1.2"/>'
        )
        short = text if len(text) <= 26 else text[:25] + "…"
        parts.append(
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="14" '
            f'fill="var(--lc-ink)"><tspan font-weight="600">{name.upper()}</tspan> '
            f"{escape(short)}<title>{escape(text)}</title></text>"
        )
    height = 380 if "w" in labels else 280
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
