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
            "does not apply. With several studies chosen, each study is a group with its own "
            "means and variances, their nth waves side by side, and two more models hold the "
            "lagged paths equal across the studies."
        )

        def offered() -> list[str]:
            return pm.panel_studies(result, view.panel_x, view.panel_y)

        def chosen_studies() -> list[str]:
            studies = offered()
            return [s for s in view.panel_studies if s in studies] or studies[:1]

        def waves_of() -> tuple[list[str], list[list[tuple[str, str, str]]], str]:
            # The waves' names, each study's waves, and why they cannot be fitted.
            studies = chosen_studies()
            if view.panel_x == view.panel_y:
                return [], [], "Choose two different variables."
            if not studies:
                found = pm.common_waves(result, view.panel_x, view.panel_y)
                return (
                    [],
                    [],
                    (
                        f"These two share {len(found)} waves of one study; the model needs "
                        f"{pm.MIN_WAVES} or more."
                    ),
                )
            each = [pm.common_waves(result, view.panel_x, view.panel_y, s) for s in studies]
            counts = {len(w) for w in each}
            if len(counts) > 1:
                named = ", ".join(
                    f"{study_label(s)} {len(w)}" for s, w in zip(studies, each, strict=True)
                )
                return (
                    [],
                    [],
                    (
                        f"The studies share different numbers of waves ({named}); choose studies "
                        "with as many waves each."
                    ),
                )
            names = ["/".join(dict.fromkeys(w[i][0] for w in each)) for i in range(len(each[0]))]
            return names, each, ""

        def study_label(study: str) -> str:
            return result.project.config.studies[study].label or study

        def choose(name: str, value) -> None:
            setattr(view, name, value)
            studies_row.refresh()
            body.clear()
            with body:
                preview()

        def preview() -> None:
            names, _, problem = waves_of()
            if problem:
                note(problem)
            else:
                ui.html(diagram(names, None), sanitize=False).classes("w-full")

        async def fit() -> None:
            rscript = analysis_tables.rscript()
            body.clear()
            if not rscript:
                with body:
                    note("Set the path to Rscript on the Settings page; the model runs in R only.")
                return
            names, each, problem = waves_of()
            if problem:
                with body:
                    preview()
                return
            # Study by study, so the data's study numbers follow the chosen order.
            datasets = list(dict.fromkeys(n for waves in each for _, x, y in waves for n in (x, y)))
            sample = analysis.build_sample(result, datasets, False)
            data = script.AnalysisData(result, sample)

            def variables(key: str, spot: int) -> list[script.Variable]:
                # The nth wave of every study as one variable, each person's from their study.
                files = ["+".join(w[i][spot] for w in each) for i in range(len(names))]
                return [data.variable(f"{key}@{f}") for f in files]

            studies = chosen_studies()
            model = pm.PanelModel(
                choices[view.panel_x],
                choices[view.panel_y],
                names,
                variables(view.panel_x, 1),
                variables(view.panel_y, 2),
                [study_label(s) for s in studies] if len(studies) > 1 else [],
            )
            frame = data.frame()
            code = pm.panel_code(model)
            with body:
                ui.spinner()
                note(f"Fitting the {len(model.models)} models in R.")
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
            if model.grouped:
                note(
                    f"The diagram gives {model.studies[0]}'s paths; the tables give every study's."
                )
            legend = f"X = {model.x_label}; Y = {model.y_label}."
            papers = {
                "panel_fit": PaperTable(
                    "Fit of the Cross-Lagged Panel Models",
                    *fit_table(model, found),
                    fit_note(found),
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
            results_text(results.panel_text(model, found, common.decimals()), list(papers.values()))
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

        @ui.refreshable
        def studies_row() -> None:
            studies = offered()
            if len(studies) < 2:
                return
            ui.select(
                {s: study_label(s) for s in studies},
                value=chosen_studies(),
                multiple=True,
                label="Studies",
                on_change=lambda e: choose("panel_studies", e.value or []),
            ).props("dense outlined use-chips").classes("w-full")

        studies_row()
        body = ui.column().classes("w-full gap-2")
        with body:
            preview()


LAGGED_NOTE = (
    "β is fully standardized. Equal paths are held equal unstandardized, so β still varies "
    "with each wave's variances."
)


def fit_table(model: pm.PanelModel, found: pm.PanelFit) -> tuple[list[dict], list[dict]]:
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
    for name, label in model.models.items():
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
        ("studies", "Paths equal across studies against free ones"),
        ("equal_studies", "Paths equal across waves and studies against equal across waves"),
    ):
        if key not in found.tests:
            continue
        chisq, df, p = found.tests[key]
        parts.append(f"{phrase}: Δχ²({df:g}) = {fmt(chisq)}, {results.p_text(p)}")
    return (
        f"N = {found.n}; MLR with robust fit indices and full-information maximum likelihood. "
        f"{'; '.join(parts)} (scaled differences; the test of the CLPM sets variances at zero, "
        "at the boundary, so its p is conservative)."
    )


LAGGED_COLUMNS = {
    pm.RICLPM: "RI-CLPM",
    pm.EQUAL: "Equal paths",
    pm.CLPM: "CLPM",
    pm.STUDIES: "Equal across studies",
    pm.EQUAL_STUDIES: "Equal across waves and studies",
}


def lagged_table(model: pm.PanelModel, found: pm.PanelFit) -> tuple[list[dict], list[dict]]:
    fitted = [m for m in LAGGED_COLUMNS if m in model.models]
    columns = [col("path", "Path")]
    for name in fitted:
        columns += [
            col(f"{name}_b", f"{LAGGED_COLUMNS[name]} β", numeric=True),
            col(f"{name}_p", "p", numeric=True),
        ]
    rows = []
    for group, study in enumerate(model.studies or [""], start=1):
        for kind, label in ROWS.items():
            for spot, path in enumerate(found.lagged(pm.RICLPM, kind, group)):
                waves = f"wave {model.waves[path.wave - 2]} to {model.waves[path.wave - 1]}"
                row = {"path": f"{f'{study}: ' if study else ''}{label}, {waves}"}
                for name in fitted:
                    same = found.lagged(name, kind, group)[spot]
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
    for group, study in enumerate(model.studies or [""], start=1):
        for label, lhs, rhs in pairs:
            found_pair = found.correlation(pm.RICLPM, lhs, rhs, group)
            if found_pair is not None:
                rows.append(
                    {
                        "what": f"{study}: {label}" if study else label,
                        "r": fmt(found_pair.standardized),
                        "p": p_value(found_pair.p),
                    }
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
    chosen = found.chosen if found is not None else pm.RICLPM

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
