from collections.abc import Callable

import pandas as pd
from nicegui import run, ui

from labcatalog import analysis
from labcatalog import analysis_script as script
from labcatalog.analysis_script import AnalysisData, Code, Comparison
from labcatalog.charts import plots, style, views
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import analysis as page
from labcatalog.gui import charts, preferences
from labcatalog.gui.common import apa, col, note, section, table
from labcatalog.pipeline import CatalogResult

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
            columns, shown = table_one_table(found["table1"], sample.datasets, labels)

            def content() -> None:
                table(columns, shown)
                note(
                    f"M (SD) for numbers and scores on everyone with a value, α on everyone "
                    f"who answered every item, n (%) of those who answered. {engine}"
                )
                page.csv_button(columns, shown, "table1.csv")

            return content

        later(fill)

    def set_measures(value: list[str] | None) -> None:
        view.measures = value or []
        body.refresh()

    section("Table 1")
    ui.select(
        choices,
        multiple=True,
        value=view.measures,
        label="Variables",
        with_input=True,
        on_change=lambda e: set_measures(e.value),
    ).props("dense outlined use-chips").classes("w-full")
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
            group_columns, group_rows = group_table(comparison)
            test_columns, test_rows = test_table(comparison)

            def content() -> None:
                with ui.row().classes("w-full gap-6 items-start"):
                    with charts.figure_column(fig):
                        page.image_buttons(charts.show(fig), fig, "groups")
                    with charts.rest_column():
                        table(group_columns, group_rows)
                        table(test_columns, test_rows)
                        left = ", ".join(f"{text} ({n})" for text, n in comparison.left_out)
                        text = f"Left out, fewer than two people: {left}. " if left else ""
                        note(f"{text}{engine}")
                        page.csv_button(group_columns, group_rows, "groups.csv")
                        page.csv_button(test_columns, test_rows, "group_test.csv")

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


def test_table(comparison: Comparison) -> tuple[list[dict], list[dict]]:
    welch = comparison.test == "welch"
    columns = [
        col("test", "Test", sortable=False),
        col("statistic", "t" if welch else "F", numeric=True),
        col("df", "df", numeric=True),
        col("p", "p", numeric=True),
        col("effect", "d" if welch else "η²", numeric=True),
    ]
    if welch:
        columns.append(col("ci", "Difference [95% CI]", numeric=True, sortable=False))
    row = {
        "test": TESTS[comparison.test],
        "statistic": decimal(comparison.statistic),
        "df": f"{comparison.df1:.1f}" if welch else f"{comparison.df1:g}, {comparison.df2:g}",
        "p": page.p_value(comparison.p),
        "effect": decimal(comparison.effect) if welch else apa(comparison.effect),
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
        f"you press the button. Save the data as {script.DATA_FILE} beside the script, then run it."
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
            with ui.row().classes("gap-2"):
                download("Data CSV", frame.to_csv(index=False), script.DATA_FILE, "text/csv")
                download("R script", r_text, "analysis.R", "text/plain")
                download("Python script", python_text, "analysis.py", "text/x-python")
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


def download(label: str, text: str, filename: str, media: str) -> None:
    content = text.encode("utf-8")
    ui.button(
        label, icon="download", on_click=lambda: ui.download.content(content, filename, media)
    ).props("flat dense no-caps")


def decimal(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"
