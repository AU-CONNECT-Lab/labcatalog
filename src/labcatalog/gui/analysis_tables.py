from collections.abc import Callable

import pandas as pd
from nicegui import run, ui

from labcatalog import analysis
from labcatalog import analysis_script as script
from labcatalog.analysis_script import AnalysisData, Code, Comparison
from labcatalog.charts import plots, style, views
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import analysis as page
from labcatalog.gui import charts, paper, preferences
from labcatalog.gui.common import apa, col, note, p_value, section
from labcatalog.pipeline import CatalogResult
from labcatalog.tables import PaperTable

TESTS = {"welch": "Welch's t test", "anova": "One-way ANOVA"}
# Answer options sit under their question; plain spaces would collapse in the page.
INDENT = " " * 4
GROUP_WIDTH = 110
FIGURE_MIN_WIDTH = 360


def rscript() -> str | None:
    return preferences.load().get(preferences.RSCRIPT) or None


async def compute(
    result: CatalogResult, sample: analysis.Sample, frame: pd.DataFrame, code: Code
) -> tuple[dict[str, pd.DataFrame], str]:
    path = rscript()
    try:
        found, engine = await run.io_bound(script.run_code, result, sample, frame, code, path)
    except LabCatalogError as err:
        if not path:
            raise
        found, _ = await run.io_bound(script.run_code, result, sample, frame, code, None)
        return found, f"R failed, so this was computed in Python: {err}"
    if engine == script.R:
        return found, "Computed in R."
    return found, "Computed in Python; set Rscript on the Settings page to compute in R."


def later(fill: Callable) -> ui.column:
    # Results that may wait for R fill in after the rest of the page shows.
    holder = ui.column().classes("w-full gap-2")
    with holder:
        ui.spinner(size="sm")

    async def run_fill() -> None:
        content = await fill()
        if holder.is_deleted:
            return
        holder.clear()
        with holder:
            content()

    ui.timer(0, run_fill, once=True)
    return holder


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
            found, engine = await compute(result, sample, data.frame(), code)
            columns, rows = table_one_table(found["table1"], sample.datasets, labels)
            shown = PaperTable(
                "Descriptive Statistics",
                columns,
                rows,
                "M (SD) for numbers and scores on everyone with a value, α on everyone who "
                "answered every item, n (%) of those who answered.",
            )

            def content() -> None:
                paper.paper_table(shown)
                note(engine)
                paper.save_button(result, "table1", {"table1": shown})

            return content

        later(fill)

    def set_measures(value: list[str] | None) -> None:
        view.measures = value or []
        body.refresh()

    section("Table 1")
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
        page.pick_menu(chosen, views.wave_groups(result, sample.datasets, script.measures))
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
    sd = "" if pd.isna(cell["sd"]) else f" ({cell['sd']:.2f})"
    return f"{cell['mean']:.2f}{sd}"


def group_section(
    result: CatalogResult, sample: analysis.Sample, view, scores: dict[str, str]
) -> None:
    labels = {name: views.dataset_label(result, name) for name in sample.datasets}
    groups = script.group_choices(result, sample.datasets, labels)
    section("Group comparison")
    if not groups or not scores:
        note("Needs a demographics item with answer options and a score in the chosen datasets.")
        return
    if view.group not in groups:
        view.group = next(iter(groups))
    if view.outcome not in scores:
        view.outcome = next(iter(views.total_choices(result, sample.datasets) or scores))

    @ui.refreshable
    def body() -> None:
        async def fill() -> Callable:
            data = AnalysisData(result, sample)
            group = data.item(view.group)
            outcome = data.score(view.outcome)
            frame = data.frame()
            plan = script.comparison_plan(frame, group, outcome)
            if plan is None:
                return lambda: note("Fewer than two groups have two or more people with a score.")
            found, engine = await compute(result, sample, frame, plan.code)
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
                with ui.row().classes("w-full gap-6 items-start"):
                    with charts.figure_column(fig):
                        drawn = paper.Chart(charts.show(fig), fig)
                    with charts.rest_column():
                        for shown in papers.values():
                            paper.paper_table(shown)
                        note(engine)
                        paper.save_button(result, "groups", papers, drawn)

            return content

        later(fill)

    def choose_group(value: str) -> None:
        view.group = value
        body.refresh()

    def choose_outcome(value: str) -> None:
        view.outcome = value
        body.refresh()

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
            label="Score",
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
    if comparison.test == "welch":
        first, second = comparison.groups[0], comparison.groups[1]
        return (
            "d is Cohen's d with the pooled SD; the difference is "
            f"{first.label} minus {second.label}, with its 95% confidence interval."
        )
    return "η² with its 95% confidence interval."


def test_table(comparison: Comparison) -> tuple[list[dict], list[dict]]:
    welch = comparison.test == "welch"
    columns = [
        col("test", "Test", sortable=False),
        col("statistic", "t" if welch else "F", numeric=True),
        col("df", "df", numeric=True),
        col("p", "p", numeric=True),
        col("effect", "d [95% CI]" if welch else "η² [95% CI]", numeric=True, sortable=False),
    ]
    if welch:
        columns.append(col("ci", "Difference [95% CI]", numeric=True, sortable=False))
    shown = decimal if welch else apa
    interval = (
        f" [{shown(comparison.effect_low)}, {shown(comparison.effect_high)}]"
        if comparison.effect_low is not None
        else ""
    )
    row = {
        "test": TESTS[comparison.test],
        "statistic": decimal(comparison.statistic),
        "df": f"{comparison.df1:.1f}" if welch else f"{comparison.df1:g}, {comparison.df2:g}",
        "p": p_value(comparison.p),
        "effect": f"{shown(comparison.effect)}{interval}",
    }
    if welch:
        first, second = comparison.groups[0], comparison.groups[1]
        row["ci"] = (
            f"{decimal(first.mean - second.mean)} "
            f"[{decimal(comparison.low)}, {decimal(comparison.high)}]"
        )
    return columns, [row]


def script_section(
    result: CatalogResult, sample: analysis.Sample, view, scores: dict[str, str]
) -> None:
    section("Script")
    note(
        "The tables above as one R script and one Python script, for the choices made when "
        f"you press the button. Saving puts the data beside them as {script.DATA_FILE}, "
        "so either script runs in that folder."
    )

    def write() -> None:
        found = script.page_script(
            result,
            sample,
            measures=view.measures,
            scores=[k for k in view.scores if k in scores],
            xs=[k for k in view.xs if k in scores],
            y=view.y if view.y in scores else None,
            group=view.group,
            outcome=view.outcome if view.outcome in scores else None,
        )
        holder.clear()
        with holder:
            if found is None:
                note("Nothing above to write a script for yet.")
                return
            r_text, python_text, frame = found
            texts = {
                script.DATA_FILE: frame.to_csv(index=False),
                "analysis.R": r_text,
                "analysis.py": python_text,
            }
            paper.save_button(result, "script", texts=texts)
            with ui.tabs().props("dense no-caps align=left") as tabs:
                ui.tab("r", label="R")
                ui.tab("python", label="Python")
            with ui.tab_panels(tabs, value="r").classes("w-full"):
                with ui.tab_panel("r").classes("p-0"):
                    ui.code(r_text, language="r").classes("w-full")
                with ui.tab_panel("python").classes("p-0"):
                    ui.code(python_text, language="python").classes("w-full")

    ui.button("Write script", icon="code", on_click=write).classes("w-fit")
    holder = ui.column().classes("w-full gap-2")


def decimal(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"
