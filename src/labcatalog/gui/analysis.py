import base64
import json
import urllib.parse
from dataclasses import dataclass, field
from functools import partial

import pandas as pd
import plotly.graph_objects as go
from nicegui import ui

from labcatalog import analysis
from labcatalog.charts import views
from labcatalog.config import dataset_by_name
from labcatalog.gui import charts
from labcatalog.gui.common import col, heading, note, section, table
from labcatalog.pipeline import CatalogResult

STARS = ((0.001, "***"), (0.01, "**"), (0.05, "*"))
IMAGE_WIDTH = 900


@dataclass
class AnalysisView:
    datasets: list[str] = field(default_factory=list)
    intersect: bool = True
    scores: list[str] = field(default_factory=list)
    xs: list[str] = field(default_factory=list)
    y: str | None = None


def render(result: CatalogResult, view: AnalysisView) -> None:
    names = views.dataset_order(result, [d.name for d in result.project.config.datasets])
    view.datasets = [n for n in view.datasets if n in names] or first_wave(result, names)

    @ui.refreshable
    def tools() -> None:
        sample = analysis.build_sample(result, view.datasets, view.intersect)
        sample_note(result, sample, view.intersect)
        choices = views.variable_choices(result, view.datasets)
        if len(choices) < 2:
            note("Pick datasets with at least two scores between them.")
            return
        correlation_section(result, sample, view, choices)
        pair_section(result, sample, view, choices)

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


def first_wave(result: CatalogResult, names: list[str]) -> list[str]:
    config = result.project.config
    wave = (dataset_by_name(config, names[0]).study, dataset_by_name(config, names[0]).wave)
    return [
        n
        for n in names
        if (dataset_by_name(config, n).study, dataset_by_name(config, n).wave) == wave
    ]


def sample_note(result: CatalogResult, sample: analysis.Sample, intersect: bool) -> None:
    by = result.project.config.stats.correlate_by
    matched = "ID" if by in ("id", "none") else by
    where = "in every selected dataset" if intersect else "in any selected dataset"
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
            note("Pick at least two scores.")
            return
        columns, rows, pairs = correlation_table(result, sample, view.scores, choices)
        table(columns, rows)
        low, high = min(pairs), max(pairs)
        n = f"n {low}" if low == high else f"n {low} to {high}"
        note(
            f"Pearson r, each pair on everyone with both scores ({n}); "
            "* p < .05, ** p < .01, *** p < .001."
        )
        csv_button(columns, rows, "correlations.csv")

    def set_scores(value: list[str] | None) -> None:
        view.scores = value or []
        body.refresh()

    section("Correlation table")
    ui.select(
        choices,
        multiple=True,
        value=view.scores,
        label="Scores",
        with_input=True,
        on_change=lambda e: set_scores(e.value),
    ).props("dense outlined use-chips").classes("w-full")
    body()


def correlation_table(
    result: CatalogResult, sample: analysis.Sample, keys: list[str], choices: dict[str, str]
) -> tuple[list[dict], list[dict], list[int]]:
    # APA layout: numbered rows, M and SD, then r below the diagonal with stars.
    frame = analysis.table(result, sample, keys)
    matrix = analysis.correlation_matrix(frame)
    columns = [
        col("variable", "Variable"),
        col("n", "n", numeric=True),
        col("m", "M", numeric=True),
        col("sd", "SD", numeric=True),
        *[col(f"c{j}", str(j + 1), numeric=True, sortable=False) for j in range(len(keys))],
    ]
    rows = []
    for i, key in enumerate(keys):
        n, mean, sd = analysis.describe(frame[key])
        row = {"variable": f"{i + 1}. {choices[key]}", "n": n, "m": number(mean), "sd": number(sd)}
        for j in range(len(keys)):
            row[f"c{j}"] = starred(matrix[i][j]) if j < i else ("—" if j == i else "")
        rows.append(row)
    pairs = [matrix[i][j].n for i in range(len(keys)) for j in range(i)]
    return columns, rows, pairs


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
        y = analysis.values(result, sample, view.y)
        fits = {
            x: fit
            for x in view.xs
            if x != view.y
            and (fit := analysis.regress(analysis.values(result, sample, x), y)) is not None
        }
        if not fits:
            note("Too few people have an X score and the Y score.")
            return
        fig = views.pair_scatter(result, sample, list(fits), view.y)
        plot = charts.show(fig)
        image_buttons(plot, fig, "regression")
        columns, rows = fit_table(fits, choices)
        heading("Statistics")
        table(columns, rows)
        csv_button(columns, rows, "regression.csv")

    def choose_xs(value: list[str] | None) -> None:
        view.xs = value or []
        body.refresh()

    def choose_y(value: str) -> None:
        view.y = value
        body.refresh()

    section("Regression")
    with ui.row().classes("w-full items-center gap-4"):
        ui.select(
            choices,
            multiple=True,
            value=view.xs,
            label="X",
            with_input=True,
            on_change=lambda e: choose_xs(e.value),
        ).props("dense outlined use-chips").classes("min-w-96 grow")
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


def apa(value: float | None) -> str:
    # Values bounded by 1 drop the leading zero.
    if value is None:
        return ""
    return f"{value:.2f}".replace("0.", ".", 1)


def p_value(p: float | None) -> str:
    if p is None:
        return ""
    return "< .001" if p < 0.001 else f"{p:.3f}".replace("0.", ".", 1)


def starred(found: analysis.Correlation) -> str:
    if found.r is None:
        return ""
    return apa(found.r) + next((stars for cut, stars in STARS if found.p < cut), "")


def csv_button(columns: list[dict], rows: list[dict], filename: str) -> None:
    frame = pd.DataFrame(rows, columns=[c["name"] for c in columns])
    frame.columns = [c["label"] for c in columns]
    # The byte order mark lets Excel read the file as UTF-8.
    content = ("\ufeff" + frame.to_csv(index=False)).encode("utf-8")
    ui.button(
        "CSV", icon="download", on_click=lambda: ui.download.content(content, filename, "text/csv")
    ).props("flat dense no-caps")


def image_buttons(plot: ui.plotly | None, fig: go.Figure, name: str) -> None:
    if plot is None:
        return

    async def save(kind: str) -> None:
        options = {
            "format": kind,
            "width": IMAGE_WIDTH,
            "height": fig.layout.height,
            "scale": 2 if kind == "png" else 1,
        }
        # The page draws charts on a clear background, so the image comes from a copy with a white one.
        url = await ui.run_javascript(
            f"const plot = getElement({plot.id});"
            "const figure = {data: plot.$el.data, layout: {...plot.$el.layout, paper_bgcolor: 'white'}};"
            f"return await plot.Plotly.toImage(figure, {json.dumps(options)});",
            timeout=20,
        )
        header, data = url.split(",", 1)
        content = (
            base64.b64decode(data)
            if header.endswith(";base64")
            else urllib.parse.unquote(data).encode()
        )
        media = "image/png" if kind == "png" else "image/svg+xml"
        ui.download.content(content, f"{name}.{kind}", media)

    with ui.row().classes("gap-2"):
        for kind in ("png", "svg"):
            ui.button(kind.upper(), icon="image", on_click=partial(save, kind)).props(
                "flat dense no-caps"
            )
