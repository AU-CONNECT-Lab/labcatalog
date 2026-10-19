from collections.abc import Callable

from nicegui import ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import analysis as page
from labcatalog.gui import analysis_tables, paper
from labcatalog.gui.common import apa, col, computed, fmt, note, p_value, panel
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import agreement, analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats.agreement import Agreement

NO_R = "Intraclass correlations run in R: set the path to Rscript on the Settings page."


def render(result: CatalogResult, sample: analysis.Sample, view, choices: dict[str, str]) -> None:
    labels = {name: page.views.dataset_label(result, name) for name in sample.datasets}
    options = {**choices, **agreement.choices(result, sample.datasets, labels)}
    view.raters = [k for k in view.raters if k in options]

    @ui.refreshable
    def body() -> None:
        if len(view.raters) < 2:
            note("Pick two or more variables, one for each rater's ratings of the same people.")
            return
        keys = list(view.raters)

        async def fill() -> Callable:
            data = script.AnalysisData(result, sample)
            variables = [data.variable(k) for k in keys]
            frame = data.frame()
            by_study = analysis.pooling(result, sample.datasets)
            code = agreement.agreement_code(variables, by_study)
            try:
                found, engine = await run(result, sample, frame, code, variables)
            except LabCatalogError as err:
                message = str(err)
                return lambda: note(message)
            found_agreement = agreement.read_agreement(found, variables)
            names = {v.column: options[k] for k, v in zip(keys, variables, strict=True)}
            texts = analysis_tables.section_files(result, sample, frame, code)
            tables = {"agreement": table(found_agreement, names, by_study)}
            studies = dict(analysis.study_options(result, sample)) if by_study else {}
            if by_study:
                tables["study_agreement"] = study_table(found_agreement, names, studies)
            text = results.agreement_text(found_agreement, studies=studies)

            def content() -> None:
                for shown in tables.values():
                    paper.paper_table(shown)
                paper.results_text(text, list(tables.values()))
                paper.result_actions(result, "agreement", tables, None, texts, engine)
                analysis_tables.code_view(texts)

            return content

        analysis_tables.later(fill)

    def set_raters(value: list[str] | None) -> None:
        view.raters = value or []
        body.refresh()

    with panel("Rater agreement", help_text="How closely raters agree on the same people"):
        note(
            "Choose one variable for each rater. Answer options give Cohen's kappa for each pair "
            "of raters; numbers and scores give intraclass correlations."
        )
        ui.select(
            options,
            multiple=True,
            value=view.raters,
            label="Raters",
            with_input=True,
            on_change=lambda e: set_raters(e.value),
        ).props("dense outlined use-chips").classes("w-full")
        body()


async def run(result, sample, frame, code: script.Code, variables) -> tuple[dict, str]:
    if agreement.kind_of(variables) == agreement.KAPPA:
        return await analysis_tables.compute(result, sample, frame, code)
    path = analysis_tables.rscript()
    if not path:
        raise LabCatalogError(NO_R)
    found, _ = await computed(script.run_code, result, sample, frame, code, path)
    return found, analysis_tables.R_NOTE


def interval(value: float | None, low: float | None, high: float | None) -> str:
    if value is None:
        return ""
    return f"{apa(value)} [{apa(low)}, {apa(high)}]" if low is not None else apa(value)


def table(found: Agreement, names: dict[str, str], by_study: bool = False) -> PaperTable:
    if found.kind == agreement.ICC:
        columns = [
            col("type", "Type"),
            col("icc", "ICC [95% CI]", numeric=True),
            col("f", "F", numeric=True),
            col("df1", "df1", numeric=True),
            col("df2", "df2", numeric=True),
            col("p", "p", numeric=True),
        ]
        rows = [
            {
                "type": agreement.ICC_TYPES.get(r.type, r.type),
                "icc": interval(r.icc, r.low, r.high),
                "f": fmt(r.f),
                "df1": f"{r.df1:g}",
                "df2": f"{r.df2:g}",
                "p": p_value(r.p),
            }
            for r in found.icc
        ]
        text = f"On the {found.n} people with a rating (psych::ICC, as JASP gives it)."
        if by_study:
            text += (
                " Within studies: each rating less its study's mean rating, so a difference "
                "between the studies does not count as agreement."
            )
        return PaperTable("Intraclass Correlations", columns, rows, text)
    columns = [
        col("pair", "Raters"),
        col("n", "n", numeric=True),
        col("kappa", "κ [95% CI]", numeric=True),
        col("weighted", "Weighted κ [95% CI]", numeric=True),
    ]
    rows = [
        {
            "pair": f"{names.get(k.first, k.first)} and {names.get(k.second, k.second)}",
            "n": k.n,
            "kappa": interval(k.kappa, k.kappa_low, k.kappa_high),
            "weighted": interval(k.weighted, k.weighted_low, k.weighted_high),
        }
        for k in found.kappas
    ]
    if found.light is not None:
        rows.append({"pair": "Average (Light's κ)", "n": "", "kappa": apa(found.light)})
    text = (
        "Cohen's κ on everyone both raters rated; weighted κ uses quadratic weights, for "
        "ordered options."
    )
    if by_study:
        text += " The studies' people together."
    return PaperTable("Agreement Between Raters", columns, rows, text)


def study_table(found: Agreement, names: dict[str, str], studies: dict[float, str]) -> PaperTable:
    if found.kind == agreement.ICC:
        columns = [
            col("study", "Study"),
            col("n", "n", numeric=True),
            col("single", "ICC(2,1) [95% CI]", numeric=True),
            col("mean", "ICC(2,k) [95% CI]", numeric=True),
        ]
        rows = []
        for k, found_rows in (found.study_icc or {}).items():
            by_type = {r.type: r for r in found_rows}
            single, mean = by_type["ICC2"], by_type["ICC2k"]
            rows.append(
                {
                    "study": studies[k],
                    "n": found.study_n[k],
                    "single": interval(single.icc, single.low, single.high),
                    "mean": interval(mean.icc, mean.low, mean.high),
                }
            )
        text = "Each study on its own, on its people with a rating (psych::ICC)."
        return PaperTable("Intraclass Correlations in Each Study", columns, rows, text)
    columns = [
        col("study", "Study"),
        col("pair", "Raters"),
        col("n", "n", numeric=True),
        col("kappa", "κ [95% CI]", numeric=True),
        col("weighted", "Weighted κ [95% CI]", numeric=True),
    ]
    rows = [
        {
            "study": studies[k],
            "pair": f"{names.get(p.first, p.first)} and {names.get(p.second, p.second)}",
            "n": p.n,
            "kappa": interval(p.kappa, p.kappa_low, p.kappa_high),
            "weighted": interval(p.weighted, p.weighted_low, p.weighted_high),
        }
        for k, pairs in (found.study_kappas or {}).items()
        for p in pairs
    ]
    text = "Each study on its own, on its people both raters rated."
    return PaperTable("Agreement Between Raters in Each Study", columns, rows, text)
