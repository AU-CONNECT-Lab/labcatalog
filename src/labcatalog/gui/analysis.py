from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial

from nicegui import ui

from labcatalog.charts import matrices, plot_code, views
from labcatalog.config import CORRELATIONS, dataset_by_name
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import (
    agreement,
    analysis_tables,
    charts,
    common,
    group_invariance,
    measurement,
    mediation,
    missing,
    multilevel,
)
from labcatalog.gui import panel as panel_view
from labcatalog.gui.common import apa, col, empty, fmt, method_toggle, note, p_value, panel
from labcatalog.gui.paper import (
    Chart,
    measures_text,
    paper_table,
    result_actions,
    results_text,
)
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import measures, results
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis, analysis_script, imputation
from labcatalog.stats import multilevel as ml

STARS = ((0.001, "***"), (0.01, "**"), (0.05, "*"))
STARS_NOTE = "*p < .05. **p < .01. ***p < .001."
PARTS = {
    "missing": "Missing data",
    "correlation": "Correlation table",
    "regression": "Regression",
    "groups": "Group comparison",
    "agreement": "Rater agreement",
    "measurement": "Measurement model",
    "invariance": "Invariance",
    "mediation": "Mediation",
    "multilevel": "Multilevel model",
    "panel": "Cross-lagged panel",
}
# What a sample of several studies can do so far: each person's own study's file, side by side.
POOLED_PARTS = (
    "missing",
    "correlation",
    "regression",
    "groups",
    "agreement",
    "measurement",
    "invariance",
    "mediation",
    "multilevel",
)


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
    invariance_measure: str | None = None
    invariance_group: str | None = None
    # None keeps the project's stats.cfa_estimator.
    invariance_estimator: str | None = None
    missing: list[str] = field(default_factory=list)
    raters: list[str] = field(default_factory=list)
    panel_x: str | None = None
    panel_y: str | None = None
    # The imputation every section shares; None keeps the project's choice or every score.
    missing_method: str | None = None
    imputed: list[str] | None = None
    auxiliaries: list[str] = field(default_factory=list)
    imputations: int | None = None
    seed: int | None = None
    # None keeps the project's stats.correlation and stats.t_test.
    correlation: str | None = None
    t_test: str | None = None
    measurement: measurement.Choices = field(default_factory=measurement.Choices)
    mediation: mediation.Choices = field(default_factory=mediation.Choices)
    # The instruments whose variables the page offers; None until first shown, then all.
    instruments: list[str] | None = None
    part: str = "correlation"


def variables(view: AnalysisView) -> Callable[[CatalogResult, list[str]], dict[str, str]]:
    return lambda result, names: analysis.of_instruments(
        views.variable_choices(result, names), view.instruments
    )


def default_totals(result: CatalogResult, view: AnalysisView, choices: dict[str, str]) -> list[str]:
    return [k for k in views.total_choices(result, view.datasets) if k in choices]


def render(result: CatalogResult, view: AnalysisView, study: str | None = None) -> None:
    datasets = result.project.config.datasets
    names = views.dataset_order(result, [d.name for d in datasets if study in (None, d.study)])
    if not names:
        empty("No datasets yet.")
        return
    view.datasets = [n for n in view.datasets if n in names] or first_wave(result, names)
    measures = views.analysis_instruments(result)
    if view.instruments is None:
        view.instruments = list(measures)
    view.instruments = [i for i in view.instruments if i in measures]

    counted: dict[str, ui.label] = {}

    def recount() -> analysis.Sample:
        sample = analysis.build_sample(result, view.datasets, view.intersect)
        where = "in every selected dataset" if view.intersect else "in any selected dataset"
        counted["label"].set_text(sample_text(result, sample, where))
        return sample

    # Only the shown part is built, so a change of sample recomputes one analysis.
    @ui.refreshable
    def section() -> None:
        sample = recount()
        if analysis.pooling(result, view.datasets) and view.part not in POOLED_PARTS:
            with panel(PARTS[view.part]):
                note(
                    "Not yet for datasets of several studies; choose the datasets of one study, "
                    "or use Missing data, Correlation table, Regression, Group comparison, "
                    "Rater agreement, Measurement model, Invariance, Mediation or Multilevel model."
                )
            return
        if view.part == "multilevel":
            multilevel.render(result, view)
            return
        if view.part == "panel":
            panel_view.render(result, view)
            return
        choices = variables(view)(result, view.datasets)
        if view.part in ("correlation", "regression") and len(choices) < 2:
            with panel(PARTS[view.part]):
                note(
                    "Pick datasets and measures with at least two scores or numbers between "
                    "them for correlations."
                )
        elif view.part == "missing":
            missing.render(result, sample, view, choices)
        elif view.part == "agreement":
            agreement.render(result, sample, view, choices)
        elif view.part == "correlation":
            correlation_section(result, sample, view, choices)
        elif view.part == "regression":
            pair_section(result, sample, view, choices)
        elif view.part == "groups":
            analysis_tables.group_section(result, sample, view, choices)
        elif view.part == "measurement":
            totals = default_totals(result, view, choices)
            measurement.render(result, sample, view.measurement, choices, totals)
        elif view.part == "invariance":
            group_invariance.render(result, sample, view)
        elif view.part == "mediation":
            if len(choices) < 3:
                with panel(PARTS[view.part]):
                    note("Pick datasets and measures with at least three scores or numbers.")
            else:
                totals = default_totals(result, view, choices)
                mediation.render(result, sample, view.mediation, choices, totals)

    def sample_changed() -> None:
        # These models pick their own waves and people, so the sample does not refit them.
        if view.part in ("multilevel", "panel"):
            recount()
        else:
            section.refresh()

    def set_datasets(value: list[str]) -> None:
        view.datasets = [n for n in names if n in value]
        sidebar.refresh()
        sample_changed()

    def set_intersect(value: bool) -> None:
        view.intersect = value
        sample_changed()

    def set_instruments(value: list[str]) -> None:
        view.instruments = [i for i in measures if i in value]
        sidebar.refresh()
        section.refresh()

    def pick(part: str) -> None:
        view.part = part
        section.refresh()

    @ui.refreshable
    def sidebar() -> None:
        with panel("Sample"):
            counted["label"] = ui.label().classes("lc-note")
            ui.switch(
                "Only people in every selected dataset",
                value=view.intersect,
                on_change=lambda e: set_intersect(e.value),
            ).props("dense")
            for title, group in wave_groups(result, names).items():
                ticks(title, group, {n: n for n in group}, view.datasets, set_datasets)
            labels = views.instrument_names(result)
            for title, group in modality_groups(result, list(measures)).items():
                ticks(title, group, labels, view.instruments, set_instruments)

    with ui.row().classes("w-full no-wrap items-start gap-4"):
        with ui.column().classes("w-72 shrink-0 lc-sticky lc-side"):
            sidebar()
        with ui.column().classes("grow min-w-0 gap-4"):
            with (
                ui.tabs(value=view.part, on_change=lambda e: pick(e.value))
                .props("dense no-caps align=left")
                .classes("lc-subnav w-full")
            ):
                for name, label in PARTS.items():
                    ui.tab(name, label=label)
            section()


def measure_paragraphs(result: CatalogResult, keys: list[str]) -> list[str]:
    pairs = [(analysis.instrument_of(k), analysis.parts(k)[0]) for k in keys]
    return measures.paragraphs(result.project, result.catalog, result.summary, pairs)


def ticks(
    title: str,
    group: list[str],
    labels: dict[str, str],
    chosen: list[str],
    changed: Callable[[list[str]], None],
) -> None:
    def toggle(key: str, on: bool) -> None:
        changed([k for k in chosen if k != key] + ([key] if on else []))

    every = all(k in chosen for k in group)
    with ui.row().classes("w-full items-center no-wrap lc-facet"):
        ui.label(title)
        ui.space()
        rest = [k for k in chosen if k not in group]
        if len(group) > 1:
            ui.button(
                "None" if every else "All",
                on_click=lambda: changed(rest if every else rest + group),
            ).props("flat dense no-caps size=sm")
    for key in group:
        ui.checkbox(
            labels[key], value=key in chosen, on_change=lambda e, k=key: toggle(k, e.value)
        ).props("dense")


def wave_groups(result: CatalogResult, names: list[str]) -> dict[str, list[str]]:
    config = result.project.config
    groups: dict[str, list[str]] = {}
    for name in names:
        d = dataset_by_name(config, name)
        groups.setdefault(views.wave_name(result, d.study, d.wave), []).append(name)
    return groups


def modality_groups(result: CatalogResult, instrument_ids: list[str]) -> dict[str, list[str]]:
    vocab = result.project.config.vocab
    found = views.instrument_modalities(result)
    groups: dict[str, list[str]] = {}
    for instrument_id in instrument_ids:
        groups.setdefault(vocab.modality_label(found[instrument_id]), []).append(instrument_id)
    return groups


def first_wave(result: CatalogResult, names: list[str]) -> list[str]:
    config = result.project.config
    wave = (dataset_by_name(config, names[0]).study, dataset_by_name(config, names[0]).wave)
    return [
        n
        for n in names
        if (dataset_by_name(config, n).study, dataset_by_name(config, n).wave) == wave
    ]


def sample_text(result: CatalogResult, sample: analysis.Sample, where: str) -> str:
    by = result.project.config.stats.correlate_by
    matched = "ID" if by in ("id", "none") else by
    text = f"{len(sample.people)} people {where}, matched across datasets by {matched}."
    if analysis.pooling(result, sample.datasets):
        studies = len(analysis.studies_of(result, sample.datasets))
        text = (
            f"{len(sample.people)} people of {studies} studies {where} of their study, matched "
            f"by {matched} within each study. The variables are those every study has in one "
            "chosen dataset, each person's from their own study, and the analyses allow for "
            "the study."
        )
    notes = analysis.group_notes(result, sample)
    return f"{text} {notes}" if notes else text


def correlation_section(
    result: CatalogResult, sample: analysis.Sample, view: AnalysisView, choices: dict[str, str]
) -> None:
    scores = [k for k in choices if not k.startswith(analysis.ITEM_PREFIX)]
    view.scores = [k for k in view.scores if k in choices] or scores

    @ui.refreshable
    def body() -> None:
        if len(view.scores) < 2:
            note("Pick at least two variables.")
            return
        keys = list(view.scores)
        imputed = missing.imputing(result, view)
        by_study = analysis.pooling(result, sample.datasets)
        if imputed and (lacking := missing.outside(result, view, keys, choices)):
            note(lacking)
            return

        async def fill() -> Callable:
            data = analysis_script.AnalysisData(result, sample)
            variables = [data.variable(k) for k in keys]
            stats = result.project.config.stats
            method = view.correlation or stats.correlation
            coefficient = CORRELATIONS[method]
            if imputed:
                plan = missing.imputation_plan(result, view, data)
                frame = data.frame()
                try:
                    found, engine, code = await missing.pooled(
                        result,
                        sample,
                        frame,
                        plan,
                        lambda file: imputation.correlation_code(variables, method, plan, file),
                    )
                except LabCatalogError as err:
                    message = str(err)
                    return lambda: note(message)
            else:
                code = analysis_script.correlation_code(variables, method, by_study)
                frame = data.frame()
                found, engine = await analysis_tables.compute(result, sample, frame, code)
            if method == "spearman" and engine != analysis_tables.R_NOTE and not imputed:
                engine += (
                    " Spearman's p uses the t approximation here; in R, as in JASP, it is exact "
                    "when there are no ties."
                )
            columns_labels = {v.column: choices[k] for k, v in zip(keys, variables, strict=True)}

            def files() -> dict[str, str]:
                dots = view.style == "dots"
                figure = plot_code.correlation(columns_labels, coefficient, dots)
                return analysis_tables.section_files(result, sample, frame, code, figure)

            # Saving and the Code view read this one dict, so a new style updates both.
            texts = files()
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
                texts.update(files())
                chart.refresh()
                code_part.refresh()

            @ui.refreshable
            def code_part() -> None:
                analysis_tables.code_view(texts, figure=True)

            who = (
                f"pooled over {plan.m} imputed data sets for everyone ({n})"
                if imputed
                else f"each pair on everyone with both values ({n})"
            )
            if by_study:
                who += ", within studies: what is left once each study's mean is taken out"

            shown = PaperTable(
                "Correlations Among Variables",
                columns,
                rows,
                f"{coefficient}, {who}. {STARS_NOTE}",
            )
            tables = {"correlations": shown}
            if by_study:
                each = (
                    f"pooled over the {plan.m} imputed data sets, each study imputed by itself"
                    if imputed
                    else "each pair on everyone with both values"
                )
                tables["study_correlations"] = PaperTable(
                    "Correlations in Each Study",
                    *study_table(
                        analysis.study_options(result, sample),
                        analysis_script.read_study_correlations(found),
                        matrix,
                        [v.column for v in variables],
                        labels,
                    ),
                    f"{coefficient} in each study on its own, {each}; Within studies as in the "
                    f"table above. {STARS_NOTE}",
                )

            def content() -> None:
                chart()
                for table in tables.values():
                    paper_table(table)
                results_text(
                    results.correlation_text(
                        labels,
                        [analysis.instrument_of(k) for k in keys],
                        matrix,
                        method == "spearman",
                        common.decimals,
                    ),
                    [shown],
                )
                measures_text(measure_paragraphs(result, keys))
                result_actions(result, "correlations", tables, drawn, texts, engine)
                code_part()

            return content

        analysis_tables.later(fill)

    def set_scores(value: list[str] | None) -> None:
        view.scores = value or []
        body.refresh()

    def set_method(value: str) -> None:
        view.correlation = value
        body.refresh()

    with panel("Correlation table", "Every pair of the chosen variables"):
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
            pick_menu(scores, views.menu_groups(result, view.datasets, variables(view)))
            method_toggle(
                CORRELATIONS,
                view.correlation or result.project.config.stats.correlation,
                set_method,
            )
            missing.method_switch(result, view, body.refresh)
        body()


def pick_menu(select: ui.select, groups: dict[str, list[str]]) -> None:
    # Adds a set of variables to what is already chosen; Clear starts over.
    def add(keys: list[str]) -> None:
        select.set_value(list(dict.fromkeys([*(select.value or []), *keys])))

    with ui.dropdown_button("Select", auto_close=True).props("flat dense no-caps"):
        ui.item("All", on_click=lambda: add(list(select.options)))
        for label, keys in groups.items():
            ui.item(label, on_click=partial(add, keys))
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


def study_table(
    studies: list[tuple[float, str]],
    each: dict[float, dict[tuple[str, str], analysis.Correlation]],
    matrix: list[list[analysis.Correlation]],
    columns: list[str],
    labels: list[str],
) -> tuple[list[dict], list[dict]]:
    # One row per pair: its r and n in each study, then within studies.
    header = [col("pair", "Variables")]
    for k, (_, label) in enumerate(studies):
        header += [
            col(f"r{k}", f"{label} r", numeric=True, sortable=False),
            col(f"n{k}", "n", numeric=True, sortable=False),
        ]
    header.append(col("within", "Within studies r", numeric=True, sortable=False))
    rows = []
    for i in range(len(columns)):
        for j in range(i):
            row = {"pair": f"{labels[j]} with {labels[i]}", "within": starred(matrix[i][j])}
            for k, (code, _) in enumerate(studies):
                found = each.get(code, {}).get((columns[i], columns[j]))
                row[f"r{k}"] = "" if found is None else starred(found)
                row[f"n{k}"] = "" if found is None else found.n
            rows.append(row)
    return header, rows


def pair_section(
    result: CatalogResult, sample: analysis.Sample, view: AnalysisView, choices: dict[str, str]
) -> None:
    keys = list(choices)
    totals = default_totals(result, view, choices) or keys
    view.xs = [x for x in view.xs if x in choices] or totals[:1]
    if view.y not in choices or view.y in view.xs:
        view.y = next((k for k in totals + keys if k not in view.xs), keys[0])

    @ui.refreshable
    def body() -> None:
        xs, y_key = [x for x in view.xs if x != view.y], view.y
        imputed = missing.imputing(result, view)
        by_study = analysis.pooling(result, sample.datasets)
        if imputed and (lacking := missing.outside(result, view, [y_key, *xs], choices)):
            note(lacking)
            return

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
            if imputed:
                plan = missing.imputation_plan(result, view, data)
                frame = data.frame()
                predictors = list(usable.values())
                try:
                    found, engine, code = await missing.pooled(
                        result,
                        sample,
                        frame,
                        plan,
                        lambda file: imputation.regression_code(predictors, y, plan, file),
                    )
                except LabCatalogError as err:
                    message = str(err)
                    return lambda: note(message)
                who = f"fitted in each of {plan.m} imputed data sets and pooled, for everyone"
            else:
                code = analysis_script.regression_code(list(usable.values()), y, by_study)
                found, engine = await analysis_tables.compute(result, sample, frame, code)
                who = "on everyone with both values"
            if by_study:
                first = analysis.study_options(result, sample)[0][1]
                who += (
                    f", with the study as a fixed effect (the intercept is {first}'s); r is "
                    "within studies"
                )
            figure = plot_code.regression(
                {v.column: choices[x] for x, v in usable.items()}, choices[y_key]
            )
            texts = analysis_tables.section_files(result, sample, frame, code, figure)
            fits = analysis_script.read_regressions(found, {v.column: x for x, v in usable.items()})
            fig = views.pair_scatter(result, sample, list(fits), y_key)
            columns, rows = fit_table(fits, choices)
            shown = PaperTable(
                f"Simple Regressions Predicting {choices[y_key]}",
                columns,
                rows,
                f"Each row is a separate regression of the outcome on one predictor, {who}; r "
                "with its 95% confidence interval.",
            )

            def content() -> None:
                drawn = Chart(charts.show(fig), fig)
                paper_table(shown)
                results_text(
                    results.regression_text(fits, choices, choices[y_key], common.decimals),
                    [shown],
                )
                measures_text(measure_paragraphs(result, [y_key, *fits]))
                result_actions(result, "regression", {"regression": shown}, drawn, texts, engine)
                analysis_tables.code_view(texts, figure=True)

            return content

        analysis_tables.later(fill)

    def choose_xs(value: list[str] | None) -> None:
        view.xs = value or []
        body.refresh()

    def choose_y(value: str) -> None:
        view.y = value
        body.refresh()

    with panel("Regression", "The outcome Y on each predictor X, one at a time"):
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
            pick_menu(xs, views.menu_groups(result, view.datasets, variables(view)))
            ui.select(
                choices,
                value=view.y,
                label="Y",
                with_input=True,
                on_change=lambda e: choose_y(e.value),
            ).props("dense outlined").classes("w-96")
            missing.method_switch(result, view, body.refresh)
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
    return fmt(value)


def starred(found: analysis.Correlation) -> str:
    if found.r is None:
        return ""
    return apa(found.r) + next((stars for cut, stars in STARS if found.p < cut), "")
