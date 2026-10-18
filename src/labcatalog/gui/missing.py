from collections.abc import Callable

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import analysis as page
from labcatalog.gui import analysis_tables, paper
from labcatalog.gui.common import col, computed, fmt, method_toggle, note, panel
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis, imputation
from labcatalog.stats import analysis_script as script
from labcatalog.stats.analysis_script import MissingData

PATTERN_NOTE = (
    "Each row is one pattern of which variables people have (1) and lack (0), the most common "
    "first; the columns are numbered as in the table above."
)


def render(result: CatalogResult, sample: analysis.Sample, view, choices: dict[str, str]) -> None:
    scores = [k for k in choices if not k.startswith(analysis.ITEM_PREFIX)]
    view.missing = [k for k in view.missing if k in choices] or scores

    @ui.refreshable
    def body() -> None:
        if not view.missing:
            note("Pick at least one variable.")
            return
        keys = list(view.missing)

        async def fill() -> Callable:
            data = script.AnalysisData(result, sample)
            variables = [data.variable(k) for k in keys]
            frame = data.frame()
            code = script.missing_code(variables)
            found, engine = await analysis_tables.compute(result, sample, frame, code)
            missing = script.read_missing(found, [v.column for v in variables])
            labels = [choices[k] for k in keys]
            texts = analysis_tables.section_files(result, sample, frame, code)
            papers = {
                "missing": PaperTable(
                    "Missing Values by Variable",
                    *count_table(missing, labels),
                    f"Among the {missing.people} people in the sample.",
                ),
                "missing_patterns": PaperTable(
                    "Patterns of Missing Values", *pattern_table(missing), PATTERN_NOTE
                ),
            }

            def content() -> None:
                for shown in papers.values():
                    paper.paper_table(shown)
                paper.results_text(results.missing_text(missing, labels), list(papers.values()))
                paper.result_actions(result, "missing", papers, None, texts, engine)
                analysis_tables.code_view(texts)

            return content

        analysis_tables.later(fill)

    def set_variables(value: list[str] | None) -> None:
        view.missing = value or []
        body.refresh()

    with panel("Missing data", "Who has a value on each chosen variable"):
        note(
            "The correlation table, regression and group comparison use everyone with values on "
            "what each needs; each table's note gives its n."
        )
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            chosen = (
                ui.select(
                    choices,
                    multiple=True,
                    value=view.missing,
                    label="Variables",
                    with_input=True,
                    on_change=lambda e: set_variables(e.value),
                )
                .props("dense outlined use-chips")
                .classes("grow")
            )
            page.pick_menu(
                chosen, page.views.menu_groups(result, view.datasets, page.variables(view))
            )
        body()
    imputation_panel(result, sample, view, choices)


def imputation_panel(
    result: CatalogResult, sample: analysis.Sample, view, choices: dict[str, str]
) -> None:
    stats = result.project.config.stats
    scores = {k: v for k, v in choices.items() if not k.startswith(analysis.ITEM_PREFIX)}

    def keep(name: str, value) -> None:
        setattr(view, name, value)

    async def run_it() -> None:
        out.clear()
        path = analysis_tables.rscript()
        if not path:
            with out:
                note(NO_R)
            return
        with out:
            ui.spinner()
        data = script.AnalysisData(result, sample)
        plan = imputation_plan(result, view, data)
        frame = data.frame()
        code = imputation.summary_code(plan)
        try:
            found, _ = await computed(script.run_code, result, sample, frame, code, path)
        except LabCatalogError as err:
            out.clear()
            with out:
                note(str(err))
            return
        columns, events = imputation.read_summary(found)
        texts = analysis_tables.section_files(result, sample, frame, code)
        shown = PaperTable(
            "Imputed and Observed Values",
            *summary_table(columns),
            f"{plan.m} imputed data sets by predictive mean matching (mice), seed {plan.seed}; "
            "imputed values are averaged over all data sets.",
        )
        out.clear()
        with out:
            paper.paper_table(shown)
            for line in events:
                note(f"mice: {line}")
            paper.result_actions(
                result, "imputation", {"imputation": shown}, None, texts, IMPUTED_NOTE
            )
            analysis_tables.code_view(texts)

    with panel("Multiple imputation", "One imputation model for every section that uses it"):
        default = imputation.METHODS[stats.missing]
        note(
            "A section set to Multiple imputation (the project starts each from "
            f"{default.lower()}) imputes the variables below with mice in R, each score item by "
            "item and then scored again, and pools its results over the imputed data sets. "
            "Every section's code holds this same imputation, so they all use the same imputed "
            "data. Run shows the imputed values beside the observed ones."
        )
        ui.select(
            choices,
            multiple=True,
            value=imputed_keys(result, view),
            label="Imputed (scores item by item)",
            with_input=True,
            on_change=lambda e: keep("imputed", e.value or []),
        ).props("dense outlined use-chips").classes("w-full")
        ui.select(
            scores,
            multiple=True,
            value=auxiliary_keys(result, view),
            label="Other scores that help impute, imputed as they are (auxiliary variables)",
            with_input=True,
            on_change=lambda e: keep("auxiliaries", e.value or []),
        ).props("dense outlined use-chips").classes("w-full")
        with ui.row().classes("items-center gap-2"):
            ui.number(
                "Imputed data sets",
                value=view.imputations or stats.imputations,
                min=2,
                max=500,
                precision=0,
                on_change=lambda e: keep("imputations", int(e.value) if e.value else None),
            ).props("dense outlined").classes("w-40")
            ui.number(
                "Seed",
                value=stats.seed if view.seed is None else view.seed,
                precision=0,
                on_change=lambda e: keep("seed", None if e.value is None else int(e.value)),
            ).props("dense outlined").classes("w-40")
            ui.button("Run", icon="play_arrow", on_click=run_it).props("no-caps")
        out = ui.column().classes("w-full gap-2")


def summary_table(columns: list[imputation.ImputedColumn]) -> tuple[list[dict], list[dict]]:
    heads = [
        col("variable", "Variable"),
        col("missing", "Missing", numeric=True),
        col("observed", "Observed M (SD)", numeric=True),
        col("imputed", "Imputed M (SD)", numeric=True),
    ]

    def m_sd(mean: float | None, sd: float | None) -> str:
        if mean is None:
            return ""
        return f"{fmt(mean)} ({fmt(sd)})" if sd is not None else fmt(mean)

    rows = [
        {
            "variable": c.column,
            "missing": c.missing,
            "observed": m_sd(c.observed_mean, c.observed_sd),
            "imputed": m_sd(c.imputed_mean, c.imputed_sd),
        }
        for c in columns
    ]
    return heads, rows


def count_table(missing: MissingData, labels: list[str]) -> tuple[list[dict], list[dict]]:
    columns = [
        col("variable", "Variable"),
        col("n", "n", numeric=True),
        col("missing", "Missing", numeric=True),
        col("percent", "%", numeric=True),
    ]
    people = missing.people
    rows = [
        {
            "variable": f"{i + 1}. {label}",
            "n": n,
            "missing": lacking,
            "percent": f"{100 * lacking / people:.1f}" if people else "",
        }
        for i, (label, (_, n, lacking)) in enumerate(zip(labels, missing.counts, strict=True))
    ]
    return columns, rows


def pattern_table(missing: MissingData) -> tuple[list[dict], list[dict]]:
    k = len(missing.counts)
    columns = [
        *[col(f"c{j}", str(j + 1), numeric=True, sortable=False) for j in range(k)],
        col("lacking", "Missing", numeric=True),
        col("people", "People", numeric=True),
    ]
    rows = [
        {
            **{f"c{j}": int(has) for j, has in enumerate(present)},
            "lacking": k - sum(present),
            "people": people,
        }
        for present, people in missing.patterns
    ]
    return columns, rows


IMPUTED_NOTE = "Imputed and pooled in R with mice and miceadds."
NO_R = (
    "Multiple imputation runs in R: set the path to Rscript on the Settings page, or choose "
    "Available cases."
)


def imputing(result: CatalogResult, view) -> bool:
    return (view.missing_method or result.project.config.stats.missing) == imputation.IMPUTE


def method_switch(result: CatalogResult, view, on_change: Callable[[], None]) -> None:
    def choose(value: str) -> None:
        view.missing_method = value
        on_change()

    method = view.missing_method or result.project.config.stats.missing
    method_toggle(imputation.METHODS, method, choose, "Missing values")


def imputed_keys(result: CatalogResult, view) -> list[str]:
    # By default, every score of the chosen datasets, imputed item by item.
    options = page.views.variable_choices(result, view.datasets)
    if view.imputed is None:
        return [k for k in options if not k.startswith(analysis.ITEM_PREFIX)]
    return [k for k in view.imputed if k in options]


def auxiliary_keys(result: CatalogResult, view) -> list[str]:
    options = page.views.variable_choices(result, view.datasets)
    taken = set(imputed_keys(result, view))
    return [k for k in view.auxiliaries if k in options and k not in taken]


def imputation_plan(result: CatalogResult, view, data: script.AnalysisData):
    stats = result.project.config.stats
    m = view.imputations or stats.imputations
    seed = stats.seed if view.seed is None else view.seed
    keys, helpers = imputed_keys(result, view), auxiliary_keys(result, view)
    return imputation.plan(data, keys, helpers, m, seed)


def outside(result: CatalogResult, view, keys: list[str], labels: dict[str, str]) -> str:
    # What a section asks for that the imputation on the Missing data tab leaves out.
    held = set(imputed_keys(result, view)) | set(auxiliary_keys(result, view))
    lacking = [labels.get(k, k) for k in keys if k not in held]
    if not lacking:
        return ""
    return (
        f"{', '.join(lacking)} {'is' if len(lacking) == 1 else 'are'} not in the imputation; "
        "add them on the Missing data tab, or choose Available cases."
    )


async def pooled(
    result: CatalogResult, sample: analysis.Sample, frame, code: script.Code
) -> tuple[dict, str]:
    path = analysis_tables.rscript()
    if not path:
        raise LabCatalogError(NO_R)
    found, _ = await computed(script.run_code, result, sample, frame, code, path)
    return found, IMPUTED_NOTE
