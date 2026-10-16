from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from nicegui import ui

from labcatalog.charts import matrices, views
from labcatalog.config import dataset_by_name
from labcatalog.gui import analysis_tables, charts, multilevel
from labcatalog.gui.common import apa, col, note, p_value, section
from labcatalog.gui.paper import Chart, paper_table, save_button
from labcatalog.pipeline import CatalogResult
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis, analysis_script
from labcatalog.stats import multilevel as ml

STARS = ((0.001, "***"), (0.01, "**"), (0.05, "*"))
STARS_NOTE = "*p < .05. **p < .01. ***p < .001."


@dataclass
class AnalysisView:
    datasets: list[str] = field(default_factory=list)
    intersect: bool = True
    scores: list[str] = field(default_factory=list)
    style: str = "heatmap"
    xs: list[str] = field(default_factory=list)
    y: str | None = None
    group: str | None = None
    outcome: str | None = None
    multilevel: ml.Model | None = None


def render(result: CatalogResult, view: AnalysisView) -> None:
    names = views.dataset_order(result, [d.name for d in result.project.config.datasets])
    if not names:
        note("No datasets yet.")
        return
    view.datasets = [n for n in view.datasets if n in names] or first_wave(result, names)

    @ui.refreshable
    def tools() -> None:
        sample = analysis.build_sample(result, view.datasets, view.intersect)
        where = "in every selected dataset" if view.intersect else "in any selected dataset"
        sample_note(result, sample, where)
        choices = views.variable_choices(result, view.datasets)
        if len(choices) < 2:
            note("Pick datasets with at least two scores or numbers between them for correlations.")
        else:
            correlation_section(result, sample, view, choices)
            pair_section(result, sample, view, choices)
        analysis_tables.group_section(result, sample, view, choices)
        analysis_tables.script_section(result, sample, view, choices)

    def set_datasets(value: list[str] | None) -> None:
        view.datasets = value or []
        tools.refresh()

    def set_intersect(value: bool) -> None:
        view.intersect = value
        tools.refresh()

    section("Sample")
    with ui.row().classes("w-full items-center gap-4"):
        ui.select(
            {n: views.dataset_label(result, n) for n in names},
            multiple=True,
            value=view.datasets,
            label="Datasets",
            on_change=lambda e: set_datasets(e.value),
        ).props("dense outlined use-chips").classes("min-w-96 grow")
        ui.switch(
            "Only people in every selected dataset",
            value=view.intersect,
            on_change=lambda e: set_intersect(e.value),
        )
    tools()
    # Its own waves and people, so changing the sample does not refit it.
    multilevel.render(result, view)


def first_wave(result: CatalogResult, names: list[str]) -> list[str]:
    config = result.project.config
    wave = (dataset_by_name(config, names[0]).study, dataset_by_name(config, names[0]).wave)
    return [
        n
        for n in names
        if (dataset_by_name(config, n).study, dataset_by_name(config, n).wave) == wave
    ]


def sample_note(result: CatalogResult, sample: analysis.Sample, where: str) -> None:
    by = result.project.config.stats.correlate_by
    matched = "ID" if by in ("id", "none") else by
    text = f"{len(sample.people)} people {where}, matched across datasets by {matched}."
    if sample.ambiguous:
        text += f" {sample.ambiguous} rows are left out because their {matched} repeats in a file."
    note(text)


def correlation_section(
    result: CatalogResult, sample: analysis.Sample, view: AnalysisView, choices: dict[str, str]
) -> None:
    view.scores = [k for k in view.scores if k in choices] or views.total_choices(
        result, view.datasets
    )

    @ui.refreshable
    def body() -> None:
        if len(view.scores) < 2:
            note("Pick at least two variables.")
            return
        keys = list(view.scores)

        async def fill() -> Callable:
            data = analysis_script.AnalysisData(result, sample)
            variables = [data.variable(k) for k in keys]
            code = analysis_script.correlation_code(variables)
            frame = data.frame()
            found, engine = await analysis_tables.compute(result, sample, frame, code)
            texts = analysis_tables.section_files(result, sample, frame, code)
            described, matrix = analysis_script.read_correlations(
                found, [v.column for v in variables]
            )
            labels = [choices[k] for k in keys]
            columns, rows = correlation_table(described, matrix, labels)
            pairs = [matrix[i][j].n for i in range(len(matrix)) for j in range(i)]
            low, high = min(pairs), max(pairs)
            n = f"n {low}" if low == high else f"n {low} to {high}"

            drawn = Chart()

            # Switching the style redraws the chart only; the correlations stay as computed.
            @ui.refreshable
            def chart() -> None:
                fig = views.correlation_chart(result, keys, matrix, labels, view.style)
                if fig is None:
                    return
                with charts.figure_column(fig):
                    ui.toggle(
                        matrices.STYLES, value=view.style, on_change=lambda e: restyle(e.value)
                    ).props("dense no-caps")
                    drawn.plot, drawn.fig = charts.show(fig), fig

            def restyle(value: str) -> None:
                view.style = value
                chart.refresh()

            shown = PaperTable(
                "Correlations Among Variables",
                columns,
                rows,
                f"Pearson r, each pair on everyone with both values ({n}). {STARS_NOTE}",
            )

            def content() -> None:
                with ui.row().classes("w-full gap-6 items-start"):
                    chart()
                    with charts.rest_column():
                        paper_table(shown)
                        note(engine)
                        save_button(result, "correlations", {"correlations": shown}, drawn, texts)
                analysis_tables.code_view(texts)

            return content

        analysis_tables.later(fill)

    def set_scores(value: list[str] | None) -> None:
        view.scores = value or []
        body.refresh()

    section("Correlation table")
    with ui.row().classes("w-full items-center gap-2 no-wrap"):
        scores = (
            ui.select(
                choices,
                multiple=True,
                value=view.scores,
                label="Variables",
                with_input=True,
                on_change=lambda e: set_scores(e.value),
            )
            .props("dense outlined use-chips")
            .classes("grow")
        )
        pick_menu(scores, views.wave_groups(result, view.datasets, views.variable_choices))
    body()


def pick_menu(select: ui.select, groups: dict[str, list[str]]) -> None:
    # Adds a set of variables to what is already chosen; Clear starts over.
    def add(keys: list[str]) -> None:
        select.set_value(list(dict.fromkeys([*(select.value or []), *keys])))

    with ui.dropdown_button("Select", auto_close=True).props("flat dense no-caps"):
        ui.item("All", on_click=lambda: add(list(select.options)))
        if len(groups) > 1:
            for wave, keys in groups.items():
                ui.item(f"All in {wave}", on_click=partial(add, keys))
        ui.item("Clear", on_click=lambda: select.set_value([]))


def correlation_table(
    described: list[tuple[int, float | None, float | None]],
    matrix: list[list[analysis.Correlation]],
    labels: list[str],
) -> tuple[list[dict], list[dict]]:
    # APA layout: numbered rows, M and SD, then r below the diagonal with stars.
    columns = [
        col("variable", "Variable"),
        col("n", "n", numeric=True),
        col("m", "M", numeric=True),
        col("sd", "SD", numeric=True),
        *[col(f"c{j}", str(j + 1), numeric=True, sortable=False) for j in range(len(labels))],
    ]
    rows = []
    for i, (n, mean, sd) in enumerate(described):
        row = {"variable": f"{i + 1}. {labels[i]}", "n": n, "m": number(mean), "sd": number(sd)}
        for j in range(len(labels)):
            row[f"c{j}"] = starred(matrix[i][j]) if j < i else ("—" if j == i else "")
        rows.append(row)
    return columns, rows


def pair_section(
    result: CatalogResult, sample: analysis.Sample, view: AnalysisView, choices: dict[str, str]
) -> None:
    keys = list(choices)
    totals = views.total_choices(result, view.datasets) or keys
    view.xs = [x for x in view.xs if x in choices] or totals[:1]
    if view.y not in choices or view.y in view.xs:
        view.y = next((k for k in totals + keys if k not in view.xs), keys[0])

    @ui.refreshable
    def body() -> None:
        xs, y_key = [x for x in view.xs if x != view.y], view.y

        async def fill() -> Callable:
            data = analysis_script.AnalysisData(result, sample)
            y = data.variable(y_key)
            variables = {x: data.variable(x) for x in xs}
            frame = data.frame()
            usable = {
                x: v
                for x, v in variables.items()
                if analysis_script.fittable(frame, v.column, y.column)
            }
            if not usable:
                return lambda: note("Too few people have an X value and the Y value.")
            code = analysis_script.regression_code(list(usable.values()), y)
            found, engine = await analysis_tables.compute(result, sample, frame, code)
            texts = analysis_tables.section_files(result, sample, frame, code)
            fits = analysis_script.read_regressions(found, {v.column: x for x, v in usable.items()})
            fig = views.pair_scatter(result, sample, list(fits), y_key)
            columns, rows = fit_table(fits, choices)
            shown = PaperTable(
                f"Simple Regressions Predicting {choices[y_key]}",
                columns,
                rows,
                "Each row is a separate regression of the outcome on one predictor, on everyone "
                "with both values; r with its 95% confidence interval.",
            )

            def content() -> None:
                drawn = Chart(charts.show(fig), fig)
                paper_table(shown)
                note(engine)
                save_button(result, "regression", {"regression": shown}, drawn, texts)
                analysis_tables.code_view(texts)

            return content

        analysis_tables.later(fill)

    def choose_xs(value: list[str] | None) -> None:
        view.xs = value or []
        body.refresh()

    def choose_y(value: str) -> None:
        view.y = value
        body.refresh()

    section("Regression")
    with ui.row().classes("w-full items-center gap-4"):
        xs = (
            ui.select(
                choices,
                multiple=True,
                value=view.xs,
                label="X",
                with_input=True,
                on_change=lambda e: choose_xs(e.value),
            )
            .props("dense outlined use-chips")
            .classes("min-w-96 grow")
        )
        pick_menu(xs, views.wave_groups(result, view.datasets, views.variable_choices))
        ui.select(
            choices, value=view.y, label="Y", with_input=True, on_change=lambda e: choose_y(e.value)
        ).props("dense outlined").classes("w-96")
    body()


def fit_table(
    fits: dict[str, analysis.Fit], labels: dict[str, str]
) -> tuple[list[dict], list[dict]]:
    columns = [
        col("x", "X"),
        col("n", "n", numeric=True),
        col("r", "r [95% CI]", numeric=True),
        col("p", "p", numeric=True),
        col("slope", "Slope (SE)", numeric=True),
        col("intercept", "Intercept (SE)", numeric=True),
        col("r2", "R²", numeric=True),
    ]
    rows = []
    for x, fit in fits.items():
        c = fit.correlation
        interval = f" [{apa(c.low)}, {apa(c.high)}]" if c.low is not None else ""
        rows.append(
            {
                "x": labels[x],
                "n": c.n,
                "r": f"{apa(c.r)}{interval}",
                "p": p_value(c.p),
                "slope": f"{fit.slope:.3f} ({fit.slope_se:.3f})",
                "intercept": f"{fit.intercept:.3f} ({fit.intercept_se:.3f})",
                "r2": apa(c.r**2),
            }
        )
    return columns, rows


def number(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def starred(found: analysis.Correlation) -> str:
    if found.r is None:
        return ""
    return apa(found.r) + next((stars for cut, stars in STARS if found.p < cut), "")
