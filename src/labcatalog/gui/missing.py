from collections.abc import Callable

from nicegui import ui

from labcatalog.gui import analysis as page
from labcatalog.gui import analysis_tables, paper
from labcatalog.gui.common import col, note, panel
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis
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
