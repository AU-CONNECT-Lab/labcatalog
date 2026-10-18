from html import escape

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import analysis_tables, common
from labcatalog.gui.common import col, computed, fmt, note, p_value, panel
from labcatalog.gui.mediation import arrow, text_at
from labcatalog.gui.paper import paper_table, result_actions, results_text
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats import panel as pm

R_FILE = "panel.R"
ROWS = {
    "auto_x": "X → X",
    "auto_y": "Y → Y",
    "x_to_y": "X → Y",
    "y_to_x": "Y → X",
}


def render(result: CatalogResult, view) -> None:
    with panel("Cross-lagged panel", "X and Y over three or more waves, within and between people"):
        choices = analysis.of_instruments(pm.choices(result), view.instruments)
        if len(choices) < 2:
            note(
                "Needs two scores or numbers of the chosen measures, each measured at three or "
                "more waves of one study."
            )
            return
        keys = list(choices)
        if view.panel_x not in choices:
            view.panel_x = keys[0]
        if view.panel_y not in choices or view.panel_y == view.panel_x:
            other = analysis.instrument_of(view.panel_x)
            view.panel_y = next(
                (k for k in keys if analysis.instrument_of(k) != other),
                next(k for k in keys if k != view.panel_x),
            )
        note(
            "A random intercept cross-lagged panel model (RI-CLPM) separates the stable "
            "differences between people from how each person's X and Y carry over to the next "
            "wave. It is fitted with the lagged paths free and equal across waves, beside the "
            "cross-lagged panel model without random intercepts (CLPM), in R with lavaan. This "
            "section picks its own waves and keeps everyone with a value; the Sample on the left "
            "does not apply."
        )

        def choose(name: str, value: str) -> None:
            setattr(view, name, value)
            body.clear()
            with body:
                preview()

        def preview() -> None:
            waves = pm.common_waves(result, view.panel_x, view.panel_y)
            if view.panel_x == view.panel_y:
                note("Choose two different variables.")
            elif len(waves) < pm.MIN_WAVES:
                note(
                    f"These two share {len(waves)} waves of one study; the model needs "
                    f"{pm.MIN_WAVES} or more."
                )
            else:
                ui.html(diagram([w for w, _, _ in waves], None), sanitize=False).classes("w-full")

        async def fit() -> None:
            rscript = analysis_tables.rscript()
            body.clear()
            if not rscript:
                with body:
                    note("Set the path to Rscript on the Settings page; the model runs in R only.")
                return
            waves = pm.common_waves(result, view.panel_x, view.panel_y)
            if view.panel_x == view.panel_y or len(waves) < pm.MIN_WAVES:
                with body:
                    preview()
                return
            datasets = list(dict.fromkeys([x for _, x, _ in waves] + [y for _, _, y in waves]))
            sample = analysis.build_sample(result, datasets, False)
            data = script.AnalysisData(result, sample)
            model = pm.PanelModel(
                choices[view.panel_x],
                choices[view.panel_y],
                [w for w, _, _ in waves],
                [data.variable(f"{view.panel_x}@{x}") for _, x, _ in waves],
                [data.variable(f"{view.panel_y}@{y}") for _, _, y in waves],
            )
            frame = data.frame()
            code = pm.panel_code(model)
            with body:
                ui.spinner()
                note("Fitting the three models in R.")
            try:
                found, _ = await computed(script.run_code, result, sample, frame, code, rscript)
            except LabCatalogError as err:
                body.clear()
                with body:
                    note(str(err))
                return
            if body.is_deleted:
                return
            found_fit = pm.read_fit(found)
            r_text, _ = script.script(result, sample, [code])
            title = f"{model.x_label} and {model.y_label}"
            texts = {script.DATA_FILE: frame.to_csv(index=False), R_FILE: r_text}
            texts |= pm.mplus_files(model, frame, title)
            body.clear()
            with body:
                show(model, found_fit, texts)

        def show(model: pm.PanelModel, found: pm.PanelFit, texts: dict[str, str]) -> None:
            ui.html(diagram(model.waves, found), sanitize=False).classes("w-full")
            legend = f"X = {model.x_label}; Y = {model.y_label}."
            papers = {
                "panel_fit": PaperTable(
                    "Fit of the Cross-Lagged Panel Models", *fit_table(found), fit_note(found)
                ),
                "panel_paths": PaperTable(
                    "Lagged Effects", *lagged_table(model, found), f"{legend} {LAGGED_NOTE}"
                ),
                "panel_correlations": PaperTable(
                    "Correlations Between and Within People",
                    *correlation_table(model, found),
                    f"{legend} From the RI-CLPM with free lagged paths.",
                ),
            }
            for shown in papers.values():
                paper_table(shown)
            results_text(results.panel_text(model, found, common.decimals), list(papers.values()))
            result_actions(result, "panel", papers, texts=texts, engine="Computed in R.")
            with ui.expansion("Code", icon="code").props("dense").classes("w-full"):
                note(
                    f"Runs in a folder that holds {script.DATA_FILE}; Save to outputs writes it, "
                    "this script and the three models as Mplus inputs with their data."
                )
                ui.code(texts[R_FILE], language="r").classes("w-full")

        with ui.row().classes("w-full items-center gap-4"):
            ui.select(
                choices,
                value=view.panel_x,
                label="X",
                with_input=True,
                on_change=lambda e: choose("panel_x", e.value),
            ).props("dense outlined").classes("min-w-80 grow")
            ui.select(
                choices,
                value=view.panel_y,
                label="Y",
                with_input=True,
                on_change=lambda e: choose("panel_y", e.value),
            ).props("dense outlined").classes("min-w-80 grow")
            ui.button("Fit", icon="play_arrow", on_click=fit).props("no-caps")
        body = ui.column().classes("w-full gap-2")
        with body:
            preview()


LAGGED_NOTE = (
    "β is fully standardized. Equal paths are held equal unstandardized, so β still varies "
    "with each wave's variances."
)


def fit_table(found: pm.PanelFit) -> tuple[list[dict], list[dict]]:
    columns = [
        col("model", "Model"),
        col("chisq", "χ²", numeric=True),
        col("df", "df", numeric=True),
        col("p", "p", numeric=True),
        col("cfi", "CFI", numeric=True),
        col("tli", "TLI", numeric=True),
        col("rmsea", "RMSEA", numeric=True),
        col("srmr", "SRMR", numeric=True),
        col("aic", "AIC", numeric=True),
        col("bic", "BIC", numeric=True),
    ]
    rows = []
    for name, label in pm.MODELS.items():
        v = found.fits[name]
        rows.append(
            {
                "model": label,
                "chisq": fmt(v["chisq"]),
                "df": f"{v['df']:g}" if v["df"] is not None else "",
                "p": p_value(v["pvalue"]),
                **{k: fmt(v[k]) for k in ("cfi", "tli", "rmsea", "srmr")},
                "aic": f"{v['aic']:.1f}" if v["aic"] is not None else "",
                "bic": f"{v['bic']:.1f}" if v["bic"] is not None else "",
            }
        )
    return columns, rows


def fit_note(found: pm.PanelFit) -> str:
    parts = []
    for key, phrase in (
        ("equal", "Equal lagged paths against free ones"),
        ("intercepts", "The CLPM against the RI-CLPM"),
    ):
        chisq, df, p = found.tests[key]
        parts.append(f"{phrase}: Δχ²({df:g}) = {fmt(chisq)}, {results.p_text(p)}")
    return (
        f"N = {found.n}; MLR with robust fit indices and full-information maximum likelihood. "
        f"{'; '.join(parts)} (scaled differences; the second tests variances at zero, at the "
        "boundary, so its p is conservative)."
    )


def lagged_table(model: pm.PanelModel, found: pm.PanelFit) -> tuple[list[dict], list[dict]]:
    columns = [col("path", "Path")]
    for name, label in (("riclpm", "RI-CLPM"), ("equal", "Equal paths"), ("clpm", "CLPM")):
        columns += [
            col(f"{name}_b", f"{label} β", numeric=True),
            col(f"{name}_p", "p", numeric=True),
        ]
    rows = []
    for kind, label in ROWS.items():
        for spot, path in enumerate(found.lagged(pm.RICLPM, kind)):
            row = {
                "path": f"{label}, wave {model.waves[path.wave - 2]} to {model.waves[path.wave - 1]}"
            }
            for name, fitted in (("riclpm", pm.RICLPM), ("equal", pm.EQUAL), ("clpm", pm.CLPM)):
                same = found.lagged(fitted, kind)[spot]
                row[f"{name}_b"] = fmt(same.standardized)
                row[f"{name}_p"] = p_value(same.p)
            rows.append(row)
    return columns, rows


def correlation_table(model: pm.PanelModel, found: pm.PanelFit) -> tuple[list[dict], list[dict]]:
    columns = [col("what", "Correlation"), col("r", "r", numeric=True), col("p", "p", numeric=True)]
    pairs = [("Random intercepts of X and Y (between people)", "RIx", "RIy")]
    pairs += [
        (f"X and Y at wave {w} (within people)", f"wx{i}", f"wy{i}")
        for i, w in enumerate(model.waves, start=1)
    ]
    rows = []
    for label, lhs, rhs in pairs:
        found_pair = found.correlation(pm.RICLPM, lhs, rhs)
        if found_pair is not None:
            rows.append(
                {"what": label, "r": fmt(found_pair.standardized), "p": p_value(found_pair.p)}
            )
    return columns, rows


# Box size and layout of the diagram, in its own units.
BOX_W, BOX_H, GAP, LEFT = 130, 44, 250, 150
TOP_RI, TOP_X, TOP_Y, TOP_RIY = 40, 150, 330, 440


def diagram(waves: list[str], found: pm.PanelFit | None) -> str:
    # X above Y, a column per wave, each random intercept loading on its row.
    t = len(waves)
    xs = [LEFT + GAP * i for i in range(t)]
    width = xs[-1] + LEFT
    chosen = pm.EQUAL if found is not None and found.equal_holds else pm.RICLPM

    def beta(kind: str, wave: int, symbol: str) -> str:
        if found is None:
            return symbol
        path = found.lagged(chosen, kind)[wave - 2]
        return f"{symbol} = {fmt(path.standardized)}"

    def r(lhs: str, rhs: str) -> str:
        pair = found.correlation(pm.RICLPM, lhs, rhs) if found is not None else None
        return f"r = {fmt(pair.standardized)}" if pair is not None else "r"

    parts = []
    middle = (xs[0] + xs[-1]) / 2
    for top, row, label in ((TOP_RI, TOP_X, "RI X"), (TOP_RIY, TOP_Y, "RI Y")):
        for x in xs:
            start = top + 22 if top < row else top - 22
            end = row - BOX_H / 2 if top < row else row + BOX_H / 2
            parts.append(line(middle, start, x, end))
        parts.append(ellipse(middle, top, label))
    left = xs[0] - BOX_W / 2 - 40
    parts.append(
        f'<path d="M {middle - 70} {TOP_RI} C {left - 60} {TOP_RI}, {left - 60} {TOP_RIY}, '
        f'{middle - 70} {TOP_RIY}" fill="none" stroke="var(--lc-ink)" stroke-width="1.2" '
        'marker-start="url(#lc-head)" marker-end="url(#lc-head)"/>'
    )
    parts.append(text_at(left - 30, (TOP_RI + TOP_RIY) / 2, r("RIx", "RIy")))
    for i, x in enumerate(xs, start=1):
        side = x - BOX_W / 2 - 14
        parts.append(
            f'<line x1="{side}" y1="{TOP_X + BOX_H / 2}" x2="{side}" y2="{TOP_Y - BOX_H / 2}" '
            'stroke="var(--lc-muted)" stroke-width="1.2" marker-start="url(#lc-head)" '
            'marker-end="url(#lc-head)"/>'
        )
        parts.append(text_at(side - 30, (TOP_X + TOP_Y) / 2, r(f"wx{i}", f"wy{i}")))
        if i == 1:
            continue
        before = xs[i - 2]
        parts.append(arrow(before + BOX_W / 2, TOP_X, x - BOX_W / 2, TOP_X))
        parts.append(text_at((before + x) / 2, TOP_X - 12, beta("auto_x", i, "a")))
        parts.append(arrow(before + BOX_W / 2, TOP_Y, x - BOX_W / 2, TOP_Y))
        parts.append(text_at((before + x) / 2, TOP_Y + 24, beta("auto_y", i, "a")))
        x1, x2 = before + BOX_W / 2, x - BOX_W / 2
        parts.append(arrow(x1, TOP_X + BOX_H / 2, x2, TOP_Y - BOX_H / 2))
        parts.append(arrow(x1, TOP_Y - BOX_H / 2, x2, TOP_X + BOX_H / 2))
        # Each cross-lagged label sits near the start of its arrow, clear of the crossing.
        parts.append(text_at(x1 + 52, TOP_X + BOX_H / 2 + 34, beta("x_to_y", i, "c")))
        parts.append(text_at(x1 + 52, TOP_Y - BOX_H / 2 - 24, beta("y_to_x", i, "c")))
    for x, wave in zip(xs, waves, strict=True):
        parts.append(box(x, TOP_X, f"X, wave {wave}"))
        parts.append(box(x, TOP_Y, f"Y, wave {wave}"))
    height = TOP_RIY + 40
    return (
        f'<svg viewBox="0 0 {width} {height}" style="max-height: {height}px; width: 100%" '
        'role="img" aria-label="Path diagram of the random intercept cross-lagged panel model">'
        '<defs><marker id="lc-head" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" '
        'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
        'fill="var(--lc-ink)"/></marker></defs>' + "".join(parts) + "</svg>"
    )


def box(cx: float, cy: float, text: str) -> str:
    return (
        f'<rect x="{cx - BOX_W / 2}" y="{cy - BOX_H / 2}" width="{BOX_W}" height="{BOX_H}" '
        'rx="6" fill="var(--lc-surface)" stroke="var(--lc-ink)" stroke-width="1.2"/>'
        f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="14" '
        f'fill="var(--lc-ink)">{escape(text)}</text>'
    )


def ellipse(cx: float, cy: float, text: str) -> str:
    return (
        f'<ellipse cx="{cx}" cy="{cy}" rx="70" ry="22" fill="var(--lc-surface)" '
        'stroke="var(--lc-ink)" stroke-width="1.2"/>'
        f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="14" font-weight="600" '
        f'fill="var(--lc-ink)">{escape(text)}</text>'
    )


def line(x1: float, y1: float, x2: float, y2: float) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="var(--lc-faint)" '
        'stroke-width="1" marker-end="url(#lc-head)"/>'
    )
