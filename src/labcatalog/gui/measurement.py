from dataclasses import dataclass

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
        texts = mm.script_files(found.model, used, found.labels, names)
        texts |= mplus.cfa_files([found.model], used, names)
        if fit.problem:
            note(f"The model could not be used: {fit.problem}.")
        else:
            method = (
                f"lavaan, {estimator_text(used)}, the {fit.n} people of the sample who answered "
                "every item; factors identified by their variances."
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
        controls()
        body = ui.column().classes("w-full gap-2")


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
