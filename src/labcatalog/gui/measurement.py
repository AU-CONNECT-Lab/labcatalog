from dataclasses import dataclass
from html import escape

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common, preferences
from labcatalog.gui.common import col, computed, fmt, note, p_value, panel
from labcatalog.gui.instruments import rmsea_text
from labcatalog.gui.paper import paper_table, result_actions, results_text
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis, cfa, mplus
from labcatalog.stats import measurement as mm
from labcatalog.stats.cfa import ESTIMATORS, ML, WLSMV, CfaFit, estimator_text


@dataclass
class Choices:
    # None until first shown, then the chosen measures' totals.
    keys: list[str] | None = None
    # None keeps the project's stats.cfa_estimator.
    estimator: str | None = None


def render(
    result: CatalogResult,
    sample: analysis.Sample,
    chosen: Choices,
    choices: dict[str, str],
    totals: list[str],
) -> None:
    offered = mm.offered(result, choices)
    if chosen.keys is None:
        chosen.keys = first_dataset([k for k in totals if k in offered])
    chosen.keys = [k for k in chosen.keys if k in offered]

    def estimator(ordinal: bool) -> str:
        wanted = chosen.estimator or result.project.config.stats.cfa_estimator
        return ML if wanted == WLSMV and not ordinal else wanted

    async def run() -> None:
        rscript = preferences.load().get(preferences.RSCRIPT)
        body.clear()
        if not rscript:
            with body:
                note("Set the path to Rscript on the Settings page; the model runs in R only.")
            return
        found = mm.plan(result, sample, chosen.keys)
        if found.problem:
            with body:
                note(found.problem)
            return
        used = estimator(found.ordinal)
        with body:
            ui.spinner()
            note(f"Fitting in R, {len(found.model.data)} people with every item.")
        try:
            [fit] = await computed(cfa.fit_models, [found.model], rscript, used)
        except LabCatalogError as err:
            body.clear()
            with body:
                note(str(err))
            return
        if body.is_deleted:
            return
        body.clear()
        with body:
            show(found, fit, used)

    def show(found: mm.Plan, fit: CfaFit, used: str) -> None:
        names = ", ".join(found.labels.values())
        texts = mm.script_files(found.model, used, found.labels | found.covariates, names)
        texts |= mplus.cfa_files([found.model], used, names)
        if fit.problem:
            note(f"The model could not be used: {fit.problem}.")
        else:
            method = (
                f"lavaan, {estimator_text(used)}, the {fit.n} people of the sample who answered "
                "every item; factors identified by their variances."
            )
            if found.covariates:
                method += (
                    " Every factor is regressed on the study, so the loadings are of the pooled "
                    "sample and the factor correlations are within studies; ω comes from the same "
                    "factors fitted without the study, as semTools takes no covariates."
                )
            papers = {
                "measurement_fit": PaperTable(
                    "Fit of the Measurement Model", *fit_table(fit), method
                ),
                "measurement_loadings": PaperTable(
                    "Standardized Loadings and ω",
                    *loading_table(fit, found.labels),
                    f"{method} {omega_note(used)}",
                ),
                "measurement_correlations": PaperTable(
                    "Factor Correlations",
                    *correlation_table(fit, found.labels),
                    "Standardized correlations between the factors, with 95% confidence intervals.",
                ),
            }
            ui.html(diagram(found.model.factors, found.labels, fit), sanitize=False).classes(
                "w-full"
            )
            for shown in papers.values():
                paper_table(shown)
            results_text(
                results.cfa_text([fit], found.labels, common.decimals), list(papers.values())
            )
            result_actions(result, "measurement", papers, texts=texts, engine="Computed in R.")
        with ui.expansion("Code", icon="code").props("dense").classes("w-full"):
            note(
                f"Runs in a folder that holds {mm.DATA_FILE}; Save to outputs writes both, with "
                "the Mplus input."
            )
            ui.code(texts[mm.SCRIPT_FILE], language="r").classes("w-full")

    def choose(name: str, value) -> None:
        setattr(chosen, name, value)
        controls.refresh()
        body.clear()
        with body:
            preview()

    def preview() -> None:
        # The model's shape before it is fitted, or why it cannot be.
        found = mm.plan(result, sample, chosen.keys)
        if found.problem:
            note(found.problem)
            return
        ui.html(diagram(found.model.factors, found.labels, None), sanitize=False).classes("w-full")

    @ui.refreshable
    def controls() -> None:
        ordinal = mm.ordinal(result, chosen.keys)
        with ui.row().classes("w-full items-center gap-4"):
            ui.select(
                offered,
                value=chosen.keys,
                label="Factors",
                multiple=True,
                with_input=True,
                on_change=lambda e: choose("keys", [k for k in offered if k in (e.value or [])]),
            ).props("dense outlined use-chips").classes("min-w-64 grow")
            ui.toggle(
                {e: ESTIMATORS[e] for e in ((WLSMV, ML, cfa.MLR) if ordinal else (ML, cfa.MLR))},
                value=estimator(ordinal),
                on_change=lambda e: choose("estimator", e.value),
            ).props("dense no-caps")
            ui.button("Fit", icon="play_arrow", on_click=run).props("no-caps")
        if not ordinal:
            note("Some items are numbers, not answer options, so WLSMV is not offered.")

    with panel(
        "Measurement model",
        "Several scores, each a factor of its items, fitted together on the Sample",
    ):
        note(
            "Each chosen score becomes a factor of its own items, and the factors correlate "
            "freely: the measurement model to report before a structural model. Scores must not "
            "share items, so pick subscales or totals, not both."
        )
        if analysis.pooling(result, sample.datasets):
            note(
                "The datasets come from several studies, so every factor is regressed on the "
                "study: the factor correlations are within studies. This takes the items to work "
                "alike in every study; Invariance tests that with Study as the groups."
            )
        controls()
        body = ui.column().classes("w-full gap-2")
        with body:
            preview()


def first_dataset(keys: list[str]) -> list[str]:
    # The totals of one file to start with: across files fewer people answer every item.
    by_dataset: dict[str, list[str]] = {}
    for key in keys:
        by_dataset.setdefault(key.rsplit("@", 1)[-1], []).append(key)
    return next((found for found in by_dataset.values() if len(found) >= mm.MIN_FACTORS), keys)


def omega_note(used: str) -> str:
    if used == WLSMV:
        return "ω is semTools' categorical omega."
    return (
        "ω is the factor's share of the observed variance of the summed items, as semTools "
        "gives it for continuous items."
    )


def fit_table(fit: CfaFit) -> tuple[list[dict], list[dict]]:
    values = fit.fit
    columns = [
        col("n", "N", numeric=True),
        col("chisq", "χ² (df)", numeric=True),
        col("p", "p", numeric=True),
        col("cfi", "CFI", numeric=True),
        col("tli", "TLI", numeric=True),
        col("rmsea", "RMSEA [90% CI]", numeric=True),
        col("srmr", "SRMR", numeric=True),
    ]
    row = {
        "n": fit.n,
        "chisq": f"{fmt(values.get('chisq'))} ({values['df']:g})"
        if values.get("chisq") is not None
        else "",
        "p": p_value(values.get("p")),
        **{key: fmt(values.get(key)) for key in ("cfi", "tli", "srmr")},
        "rmsea": rmsea_text(values),
    }
    return columns, [row]


def loading_table(fit: CfaFit, labels: dict[str, str]) -> tuple[list[dict], list[dict]]:
    keys = list(fit.factors)
    columns = [
        col("item", "Item"),
        *[col(f"f{i}", labels[k], numeric=True) for i, k in enumerate(keys)],
    ]
    rows = [
        {
            "item": item,
            **{f"f{i}": fmt(fit.loadings.get((k, item))) for i, k in enumerate(keys)},
        }
        for k in keys
        for item in fit.factors[k]
    ]
    rows.append({"item": "ω", **{f"f{i}": fmt(fit.omega.get(k)) for i, k in enumerate(keys)}})
    return columns, rows


def correlation_table(fit: CfaFit, labels: dict[str, str]) -> tuple[list[dict], list[dict]]:
    # The lower triangle: each factor against those before it.
    keys = list(fit.factors)
    columns = [
        col("factor", "Factor"),
        *[col(f"f{j}", labels[k], numeric=True) for j, k in enumerate(keys[:-1])],
    ]
    rows = []
    for i, k in enumerate(keys[1:], start=1):
        row = {"factor": labels[k]}
        for j, other in enumerate(keys[:i]):
            found = fit.correlations.get((other, k)) or fit.correlations.get((k, other))
            row[f"f{j}"] = (
                f"{fmt(found['r'])} [{fmt(found['low'])}, {fmt(found['high'])}]" if found else ""
            )
        rows.append(row)
    return columns, rows


FACTOR_RX = 74
FACTOR_RY = 22
ITEM_W = 62
ITEM_H = 24
ITEM_GAP = 6
GROUP_GAP = 28
FACTOR_Y_GAP = 150
ARC_STEP = 22
MARGIN = 24
LABEL_CHARS = 22
# The diagram shrinks to the panel down to this share of its size, then scrolls.
MIN_SCALE = 0.75


def diagram(factors: dict[str, list[str]], labels: dict[str, str], fit: CfaFit | None) -> str:
    # Factors in a row with their items below them, and the factor correlations as arcs above.
    keys = list(factors)
    x, spots, items = MARGIN, {}, []
    for k in keys:
        width = len(factors[k]) * (ITEM_W + ITEM_GAP) - ITEM_GAP
        width = max(width, 2 * FACTOR_RX)
        start = x + (width - (len(factors[k]) * (ITEM_W + ITEM_GAP) - ITEM_GAP)) / 2
        for i, item in enumerate(factors[k]):
            items.append((k, item, start + i * (ITEM_W + ITEM_GAP) + ITEM_W / 2))
        spots[k] = x + width / 2
        x += width + GROUP_GAP
    width = x - GROUP_GAP + MARGIN
    arc_top = ARC_STEP * (len(keys) - 1) + 30 if len(keys) > 1 else 0
    factor_y = MARGIN + arc_top + FACTOR_RY
    item_y = factor_y + FACTOR_Y_GAP
    height = item_y + ITEM_H + MARGIN
    parts = []
    for i, a in enumerate(keys):
        for j in range(i + 1, len(keys)):
            b = keys[j]
            x1, x2 = spots[a], spots[b]
            top = factor_y - FACTOR_RY - ARC_STEP * (j - i) - 8
            parts.append(
                f'<path d="M{x1},{factor_y - FACTOR_RY} Q{(x1 + x2) / 2},{2 * top - factor_y + FACTOR_RY} '
                f'{x2},{factor_y - FACTOR_RY}" fill="none" stroke="var(--lc-muted)" '
                'stroke-width="1" marker-start="url(#lc-mm-head)" marker-end="url(#lc-mm-head)"/>'
            )
            found = (fit.correlations.get((a, b)) or fit.correlations.get((b, a))) if fit else None
            if found:
                parts.append(label_at((x1 + x2) / 2, top + 4, fmt(found["r"])))
    for k, item, cx in items:
        parts.append(
            f'<line x1="{spots[k]}" y1="{factor_y + FACTOR_RY}" x2="{cx}" y2="{item_y}" '
            'stroke="var(--lc-muted)" stroke-width="1" marker-end="url(#lc-mm-head)"/>'
        )
        parts.append(
            f'<rect x="{cx - ITEM_W / 2}" y="{item_y}" width="{ITEM_W}" height="{ITEM_H}" rx="4" '
            'fill="var(--lc-surface)" stroke="var(--lc-ink)" stroke-width="1"/>'
        )
        # The dataset a shared column name carries is the factor's own, so it is left off.
        name = item.removesuffix("_" + analysis.parts(k)[0])
        short = name if len(name) <= 10 else name[:9] + "…"
        parts.append(
            f'<text x="{cx}" y="{item_y + 16}" text-anchor="middle" font-size="11" '
            f'fill="var(--lc-ink)">{escape(short)}<title>{escape(item)}</title></text>'
        )
        if fit and (k, item) in fit.loadings:
            parts.append(label_at(cx, item_y - 6, fmt(fit.loadings[(k, item)])))
    for k in keys:
        text = labels[k]
        short = text if len(text) <= LABEL_CHARS else text[: LABEL_CHARS - 1] + "…"
        parts.append(
            f'<ellipse cx="{spots[k]}" cy="{factor_y}" rx="{FACTOR_RX}" ry="{FACTOR_RY}" '
            'fill="var(--lc-panel)" stroke="var(--lc-ink)" stroke-width="1.2"/>'
            f'<text x="{spots[k]}" y="{factor_y + 4}" text-anchor="middle" font-size="12" '
            f'font-weight="600" fill="var(--lc-ink)">{escape(short)}<title>{escape(text)}'
            "</title></text>"
        )
    # Fitted to the panel, but scrolled rather than shrunk far, so labels stay legible.
    return (
        f'<div style="overflow-x: auto"><svg style="width: 100%; min-width: '
        f'{MIN_SCALE * width:.0f}px; max-width: {width}px" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Path diagram of the measurement '
        'model"><defs><marker id="lc-mm-head" viewBox="0 0 10 10" refX="10" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 '
        'L0,10 z" fill="var(--lc-muted)"/></marker></defs>' + "".join(parts) + "</svg></div>"
    )


def label_at(x: float, y: float, text: str) -> str:
    # A number on a line, on the panel's colour so the line does not run through it.
    return (
        f'<text x="{x}" y="{y}" text-anchor="middle" font-size="11" fill="var(--lc-muted)" '
        'paint-order="stroke" stroke="var(--lc-panel)" stroke-width="4">'
        f"{escape(text)}</text>"
    )
