from collections.abc import Callable

import pandas as pd
from nicegui import ui

from labcatalog.charts import plots, style, views
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import analysis as page
from labcatalog.gui import charts, common, paper, preferences
from labcatalog.gui.common import apa, code_tabs, col, computed, fmt, note, p_value, panel
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis
from labcatalog.stats import analysis_script as script
from labcatalog.stats.analysis_script import AnalysisData, Code, Comparison

TESTS = {"welch": "Welch's t test", "student": "Student's t test", "anova": "One-way ANOVA"}
# Answer options sit under their question; plain spaces would collapse in the page.
INDENT = " " * 4
GROUP_WIDTH = 110
FIGURE_MIN_WIDTH = 360


R_NOTE = "Computed in R."


def rscript() -> str | None:
    return preferences.load().get(preferences.RSCRIPT) or None


async def compute(
    result: CatalogResult, sample: analysis.Sample, frame: pd.DataFrame, code: Code
) -> tuple[dict[str, pd.DataFrame], str]:
    path = rscript()
    try:
        found, engine = await computed(script.run_code, result, sample, frame, code, path)
    except LabCatalogError as err:
        if not path:
            raise
        found, _ = await computed(script.run_code, result, sample, frame, code, None)
        return found, f"R failed, so this was computed in Python: {err}"
    if engine == script.R:
        return found, R_NOTE
    return found, "Computed in Python; set Rscript on the Settings page to compute in R."


def section_files(
    result: CatalogResult, sample: analysis.Sample, frame: pd.DataFrame, code: Code
) -> dict[str, str]:
    # The code for one section, runnable on its own beside the data it reads.
    r_text, python_text = script.script(result, sample, [code])
    return {
        script.DATA_FILE: frame.to_csv(index=False),
        "analysis.R": r_text,
        "analysis.py": python_text,
    }


def code_view(texts: dict[str, str]) -> None:
    with ui.expansion("Code", icon="code").props("dense").classes("w-full"):
        note(f"Runs in a folder that holds {script.DATA_FILE}; Save to outputs writes both.")
        code_tabs({"r": texts["analysis.R"], "python": texts["analysis.py"]})


def later(fill: Callable) -> ui.column:
    # Results that may wait for R fill in after the rest of the page shows.
    holder = ui.column().classes("w-full gap-2")
    with holder:
        placeholder()

    async def run_fill() -> None:
        content = await fill()
        if holder.is_deleted:
            return
        holder.clear()
        with holder:
            content()

    ui.timer(0, run_fill, once=True)
    return holder


def placeholder() -> None:
    # The rough shape of a chart above a table, shown while the numbers are computed.
    with ui.column().classes("w-full gap-2"):
        ui.skeleton(height="200px").classes("w-full")
        for width in ("55%", "100%", "100%", "85%", "100%", "70%"):
            ui.skeleton("text", width=width)


def table_one_section(result: CatalogResult, sample: analysis.Sample, view) -> None:
    choices = script.measures(result, sample.datasets)
    if not choices:
        return
    view.measures = [k for k in view.measures if k in choices] or script.default_measures(
        result, sample.datasets
    )
    labels = {name: views.dataset_label(result, name) for name in sample.datasets}

    @ui.refreshable
    def body() -> None:
        if not view.measures:
            note("Pick at least one variable.")
            return

        async def fill() -> Callable:
            data = AnalysisData(result, sample)
            rows = script.measure_variables(data, view.measures, items=True)
            code = script.table_one_code(sample.datasets, rows)
            frame = data.frame()
            found, engine = await compute(result, sample, frame, code)
            texts = section_files(result, sample, frame, code)
            columns, rows = table_one_table(found["table1"], sample.datasets, labels)
            shown = PaperTable(
                "Descriptive Statistics",
                columns,
                rows,
                "M (SD) for numbers and scores on everyone with a value, α on pairwise "
                "complete cases, n (%) of those who answered.",
            )

            def content() -> None:
                paper.paper_table(shown)
                paper.result_actions(
                    result, "table1", {"table1": shown}, texts=texts, engine=engine
                )
                code_view(texts)

            return content

        later(fill)

    def set_measures(value: list[str] | None) -> None:
        view.measures = value or []
        body.refresh()

    with panel("Table 1", "Descriptive statistics of the sample"):
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            chosen = (
                ui.select(
                    choices,
                    multiple=True,
                    value=view.measures,
                    label="Variables",
                    with_input=True,
                    on_change=lambda e: set_measures(e.value),
                )
                .props("dense outlined use-chips")
                .classes("grow")
            )
            page.pick_menu(chosen, views.menu_groups(result, sample.datasets, script.measures))
        body()


def table_one_table(
    found: pd.DataFrame, datasets: list[str], labels: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    found = found.assign(level=found["level"].fillna("").astype(str))
    used = [d for d in datasets if d in set(found["dataset"])]
    with_alpha = {d: bool(found.loc[found["dataset"] == d, "alpha"].notna().any()) for d in used}
    columns = [col("variable", "Variable", sortable=False)]
    for i, name in enumerate(used):
        columns.append(col(f"d{i}", labels[name], numeric=True, sortable=False))
        if with_alpha[name]:
            columns.append(col(f"a{i}", "α", numeric=True, sortable=False))
    rows = []
    for variable in dict.fromkeys(found["variable"]):
        part = found[found["variable"] == variable]
        levels = list(dict.fromkeys(part["level"]))
        choice = levels != [""]
        if choice:
            rows.append({"variable": variable})
        for level in levels:
            row = {"variable": f"{INDENT}{level}" if choice else variable}
            for i, name in enumerate(used):
                hit = part[(part["dataset"] == name) & (part["level"] == level)]
                if hit.empty:
                    continue
                cell = hit.iloc[0]
                row[f"d{i}"] = cell_text(variable, cell, choice)
                if with_alpha[name]:
                    row[f"a{i}"] = apa(None if pd.isna(cell["alpha"]) else float(cell["alpha"]))
            rows.append(row)
    return columns, rows


def cell_text(variable: str, cell: pd.Series, choice: bool) -> str:
    if variable == "N":
        return str(int(cell["n"]))
    if choice:
        percent = "" if pd.isna(cell["percent"]) else f" ({cell['percent']:.1f}%)"
        return f"{int(cell['n'])}{percent}"
    if pd.isna(cell["mean"]):
        return ""
    sd = "" if pd.isna(cell["sd"]) else f" ({fmt(cell['sd'])})"
    return f"{fmt(cell['mean'])}{sd}"


def group_section(
    result: CatalogResult, sample: analysis.Sample, view, scores: dict[str, str]
) -> None:
    labels = {name: views.dataset_label(result, name) for name in sample.datasets}
    groups = script.group_choices(result, sample.datasets, labels)
    if not groups or not scores:
        with panel("Group comparison"):
            note(
                "Needs a demographics item with answer options and a score or number in the "
                "chosen datasets."
            )
        return
    if view.group not in groups:
        view.group = next(iter(groups))
    if view.outcome not in scores:
        view.outcome = next(iter(page.default_totals(result, view, scores) or scores))

    @ui.refreshable
    def body() -> None:
        async def fill() -> Callable:
            data = AnalysisData(result, sample)
            group = data.item(view.group)
            outcome = data.variable(view.outcome)
            frame = data.frame()
            plan = script.comparison_plan(frame, group, outcome, result.project.config.stats.t_test)
            if plan is None:
                return lambda: note("Fewer than two groups have two or more people with a value.")
            found, engine = await compute(result, sample, frame, plan.code)
            texts = section_files(result, sample, frame, plan.code)
            comparison = script.read_comparison(found, plan)
            fig = group_figure(frame, group, outcome, comparison, script.link_name(result))
            left = ", ".join(f"{text} ({n})" for text, n in comparison.left_out)
            papers = {
                "groups": PaperTable(
                    f"{outcome.label} by {groups[view.group]}",
                    *group_table(comparison),
                    f"Left out, fewer than two people: {left}." if left else "",
                ),
                "group_test": PaperTable(
                    f"{TESTS[comparison.test]} of {outcome.label}",
                    *test_table(comparison),
                    test_note(comparison),
                ),
            }

            def content() -> None:
                drawn = paper.Chart(charts.show(fig), fig)
                for shown in papers.values():
                    paper.paper_table(shown)
                paper.results_text(
                    results.comparison_text(comparison, outcome.label, common.decimals),
                    list(papers.values()),
                )
                paper.result_actions(result, "groups", papers, drawn, texts, engine)
                code_view(texts)

            return content

        later(fill)

    def choose_group(value: str) -> None:
        view.group = value
        body.refresh()

    def choose_outcome(value: str) -> None:
        view.outcome = value
        body.refresh()

    with panel("Group comparison", "An outcome across the groups of a demographics item"):
        with ui.row().classes("w-full items-center gap-4"):
            ui.select(
                groups,
                value=view.group,
                label="Groups",
                with_input=True,
                on_change=lambda e: choose_group(e.value),
            ).props("dense outlined").classes("min-w-96 grow")
            ui.select(
                scores,
                value=view.outcome,
                label="Outcome",
                with_input=True,
                on_change=lambda e: choose_outcome(e.value),
            ).props("dense outlined").classes("w-96")
        body()


def group_figure(frame, group, outcome, comparison: Comparison, link: str):
    labels = [g.label for g in comparison.groups]
    names = dict((text, value) for value, text in group.options)
    values = {}
    for i, label in enumerate(labels):
        rows = frame[(frame[group.column] == names[label]) & frame[outcome.column].notna()]
        values[i] = (rows[outcome.column].tolist(), rows[link].astype(str).tolist())
    series = [{"name": outcome.label, "color": style.group_color(0), "values": values}]
    fig = plots.score_boxes(f"{outcome.label} by group", labels, series)
    return fig.update_layout(width=max(FIGURE_MIN_WIDTH, 140 + GROUP_WIDTH * len(labels)))


def group_table(comparison: Comparison) -> tuple[list[dict], list[dict]]:
    columns = [
        col("group", "Group", sortable=False),
        col("n", "n", numeric=True),
        col("m", "M", numeric=True),
        col("sd", "SD", numeric=True),
    ]
    rows = [
        {"group": g.label, "n": g.n, "m": decimal(g.mean), "sd": decimal(g.sd)}
        for g in comparison.groups
    ]
    return columns, rows


def test_note(comparison: Comparison) -> str:
    if comparison.test != script.ANOVA:
        first, second = comparison.groups[0], comparison.groups[1]
        d = (
            "d is Cohen's d with the mean of the two group variances, as JASP gives it with "
            "Welch's test"
            if comparison.test == script.WELCH
            else "d is Cohen's d with the pooled SD, as JASP gives it with Student's test"
        )
        return (
            f"{d}, with JASP's 95% confidence interval (noncentral t). The difference is "
            f"{first.label} minus {second.label}, with its 95% confidence interval."
        )
    omega = "" if comparison.omega is not None else " ω² is computed only in R."
    return f"η² and ω² (JASP's default) with their 95% confidence intervals.{omega}"


def test_table(comparison: Comparison) -> tuple[list[dict], list[dict]]:
    two = comparison.test != script.ANOVA
    columns = [
        col("test", "Test", sortable=False),
        col("statistic", "t" if two else "F", numeric=True),
        col("df", "df", numeric=True),
        col("p", "p", numeric=True),
        col("effect", "d [95% CI]" if two else "η² [95% CI]", numeric=True, sortable=False),
    ]
    if two:
        columns.append(col("ci", "Difference [95% CI]", numeric=True, sortable=False))
    else:
        columns.append(col("omega", "ω² [95% CI]", numeric=True, sortable=False))
    shown = decimal if two else apa

    def with_interval(value, low, high) -> str:
        if value is None:
            return ""
        return f"{shown(value)} [{shown(low)}, {shown(high)}]" if low is not None else shown(value)

    row = {
        "test": TESTS[comparison.test],
        "statistic": decimal(comparison.statistic),
        "df": results.df_text(comparison),
        "p": p_value(comparison.p),
        "effect": with_interval(comparison.effect, comparison.effect_low, comparison.effect_high),
    }
    if not two:
        row["omega"] = with_interval(comparison.omega, comparison.omega_low, comparison.omega_high)
    if two:
        first, second = comparison.groups[0], comparison.groups[1]
        row["ci"] = (
            f"{decimal(first.mean - second.mean)} "
            f"[{decimal(comparison.low)}, {decimal(comparison.high)}]"
        )
    return columns, [row]


def script_section(
    result: CatalogResult, sample: analysis.Sample, view, scores: dict[str, str]
) -> None:

    def write() -> None:
        found = script.page_script(
            result,
            sample,
            scores=[k for k in view.scores if k in scores],
            xs=[k for k in view.xs if k in scores],
            y=view.y if view.y in scores else None,
            group=view.group,
            outcome=view.outcome if view.outcome in scores else None,
        )
        holder.clear()
        with holder:
            if found is None:
                note("Nothing on the other tabs to write a script for yet.")
                return
            r_text, python_text, frame = found
            texts = {
                script.DATA_FILE: frame.to_csv(index=False),
                "analysis.R": r_text,
                "analysis.py": python_text,
            }
            paper.save_button(result, "script", texts=texts)
            code_tabs({"r": r_text, "python": python_text})

    with panel(
        "Script",
        "The tables on the other tabs as one R script and one Python script, for the choices made when "
        f"you press the button. Saving puts the data beside them as {script.DATA_FILE}, "
        "so either script runs in that folder.",
    ) as tools:
        holder = ui.column().classes("w-full gap-2")
    with tools:
        ui.button("Write script", icon="code", on_click=write).props("flat no-caps").classes(
            "lc-quiet-btn"
        )


def decimal(value: float | None) -> str:
    return fmt(value)
