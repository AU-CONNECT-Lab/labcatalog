from collections.abc import Callable
from dataclasses import replace

from nicegui import ui

from labcatalog.charts import views
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import charts, paper
from labcatalog.gui.analysis_tables import decimal, later, rscript
from labcatalog.gui.common import apa, code_tabs, col, computed, note, p_value, section
from labcatalog.pipeline import CatalogResult
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis
from labcatalog.stats import multilevel as ml

ONE_EACH = (
    "Each {group} holds one person here, so the {group} and person levels cannot be told "
    "apart; turn one of them off."
)
TIME_UNITS = {
    ml.WAVES: "Waves since the first",
    "month": "Months, from the dates",
    "year": "Years, from the dates",
}
R_FILE = "multilevel.R"
PYTHON_FILE = "multilevel.py"
SINGULAR = (
    "The fit is singular: a random effect is estimated as zero or as perfectly correlated, so "
    "it cannot be estimated from these data. A simpler random structure, such as one without "
    "the random slope, may fit; JASP gives the same warning."
)


def render(result: CatalogResult, view) -> None:
    section("Multilevel model")
    outcomes = analysis.of_instruments(ml.outcome_choices(result), view.instruments)
    if not outcomes:
        note("Needs a score or number of the chosen measures in at least one dataset.")
        return
    if view.multilevel is None or view.multilevel.outcome not in outcomes:
        view.multilevel = ml.default_model(result, list(outcomes))
    labels = {name: views.dataset_label(result, name) for name in result.datasets}
    covariates = analysis.of_instruments(ml.covariate_choices(result, labels), view.instruments)
    # Covariates of measures no longer chosen leave the model too.
    kept = [k for k in view.multilevel.covariates if k in covariates]
    view.multilevel = replace(view.multilevel, covariates=kept)
    model: ml.Model = view.multilevel
    group = ml.group_name(result)
    note(
        "Waves within people, people within groups, or both, fitted the way JASP's linear "
        "mixed models are. This section picks its own waves and keeps everyone with at least "
        "one; the Sample above does not apply."
    )

    @ui.refreshable
    def body() -> None:
        found = ml.problem(result, model)
        if found:
            note(found)
            return
        long = ml.long_frame(result, model)
        label = outcomes[model.outcome]

        async def fill() -> Callable:
            fitted, engine = await fit(result, model, long, label)
            r_text, python_text = ml.scripts(result, model, long, label)
            texts = {
                ml.DATA_FILE: long.frame.to_csv(index=False),
                R_FILE: r_text,
                PYTHON_FILE: python_text,
            }
            papers = {
                "multilevel_fixed": PaperTable(
                    f"Fixed Effects for {label}", *fixed_table(fitted), fixed_note(fitted, long)
                ),
                "multilevel_random": PaperTable(
                    "Random Effects",
                    *random_table(fitted),
                    random_note(model, long),
                ),
                "multilevel_summary": PaperTable(
                    "Model Summary", *summary_table(fitted), summary_note(fitted)
                ),
            }

            def content() -> None:
                if fitted.singular:
                    ui.label(SINGULAR).classes("text-negative")
                if model.by_person and fitted.groups == fitted.people:
                    ui.label(ONE_EACH.format(group=long.group)).classes("text-negative")
                for text in fitted.notes:
                    ui.label(f"Warning: {text}").classes("text-negative")
                for shown in papers.values():
                    paper.paper_table(shown)
                fig = views.trajectories(long, fitted, label)
                drawn = paper.Chart(charts.show(fig), fig)
                note(trajectory_note(long))
                note(engine)
                paper.save_button(result, "multilevel", papers, drawn, texts)
                with ui.expansion("Code", icon="code").props("dense").classes("w-full"):
                    note(
                        f"Runs in a folder that holds {ml.DATA_FILE}, one row per person and "
                        "wave, which JASP can open too; Save to outputs writes all three."
                    )
                    code_tabs({"r": r_text, "python": python_text})

            return content

        later(fill)

    def change(**fields) -> None:
        view.multilevel = replace(view.multilevel, **fields)
        nonlocal model
        model = view.multilevel
        body.refresh()

    def choose_outcome(value: str) -> None:
        names = ml.occasions(result, value)
        study = result.project.config.datasets
        first = next(d.study for d in study if d.name == names[0])
        change(
            outcome=value,
            datasets=[n for n in names if any(d.name == n and d.study == first for d in study)],
        )
        waves.set_options({n: labels[n] for n in ml.occasions(result, value)}, value=model.datasets)

    with ui.row().classes("w-full items-center gap-4"):
        ui.select(
            outcomes,
            value=model.outcome,
            label="Outcome",
            with_input=True,
            on_change=lambda e: choose_outcome(e.value),
        ).props("dense outlined").classes("w-96")
        waves = (
            ui.select(
                {n: labels[n] for n in ml.occasions(result, model.outcome)},
                multiple=True,
                value=model.datasets,
                label="Waves",
                on_change=lambda e: change(datasets=e.value or []),
            )
            .props("dense outlined use-chips")
            .classes("min-w-96 grow")
        )
    ui.select(
        covariates,
        multiple=True,
        value=[k for k in model.covariates if k in covariates],
        label="Covariates (one dataset's value, or each wave's own)",
        with_input=True,
        on_change=lambda e: change(covariates=e.value or []),
    ).props("dense outlined use-chips").classes("w-full")
    with ui.row().classes("w-full items-center gap-6"):
        ui.select(
            TIME_UNITS,
            value=model.time,
            label="Time counts",
            on_change=lambda e: change(time=e.value),
        ).props("dense outlined").classes("w-56")
        ui.switch(
            "Waves within people",
            value=model.by_person,
            on_change=lambda e: change(by_person=e.value),
        )
        if group:
            ui.switch(
                f"People within each {group}",
                value=model.by_group,
                on_change=lambda e: change(by_group=e.value),
            )
        ui.switch(
            "Random slope of time for each person",
            value=model.slope,
            on_change=lambda e: change(slope=e.value),
        )
        if any(ml.each_wave(k) for k in model.covariates):
            ui.switch(
                "Split each-wave covariates into person mean and deviation",
                value=model.split,
                on_change=lambda e: change(split=e.value),
            )
    body()


def trajectory_note(long: ml.Long) -> str:
    text = (
        "Thin lines: each person's values. Circles: each wave's mean. Thick line: the fixed "
        "effects' prediction"
    )
    if long.covariates:
        text += (
            ", with number covariates at their mean and answer covariates at the reference option"
        )
    return text + "."


def random_note(model: ml.Model, long: ml.Long) -> str:
    text = "Variances and SDs; r is the correlation of the slope with the intercept."
    if model.by_person and model.slope and long.group and len(model.datasets) > 1:
        text += (
            " With groups as well, the slope is not correlated with the intercept, so that R "
            "and Python fit the same model."
        )
    return text


async def fit(
    result: CatalogResult, model: ml.Model, long: ml.Long, label: str
) -> tuple[ml.Fitted, str]:
    path = rscript()
    try:
        fitted = await computed(ml.run, result, model, long, label, path)
    except LabCatalogError as err:
        if not path:
            raise
        fitted = await computed(ml.run, result, model, long, label, None)
        return fitted, f"R failed, so this was computed in Python: {err}"
    if fitted.engine == ml.R:
        return fitted, "Computed in R (lme4 and lmerTest)."
    return fitted, (
        "Computed in Python (statsmodels); set Rscript on the Settings page to compute in R, "
        "with Satterthwaite df as in JASP."
    )


def fixed_table(fitted: ml.Fitted) -> tuple[list[dict], list[dict]]:
    in_r = fitted.engine == ml.R
    columns = [
        col("term", "Term", sortable=False),
        col("b", "b", numeric=True),
        col("se", "SE", numeric=True),
        *([col("df", "df", numeric=True)] if in_r else []),
        col("statistic", "t" if in_r else "z", numeric=True),
        col("p", "p", numeric=True),
        col("ci", "95% CI", numeric=True, sortable=False),
    ]
    rows = [
        {
            "term": t.label,
            "b": decimal(t.estimate),
            "se": decimal(t.se),
            "df": "" if t.df is None else f"{t.df:.1f}",
            "statistic": decimal(t.statistic),
            "p": p_value(t.p),
            "ci": f"[{decimal(t.low)}, {decimal(t.high)}]",
        }
        for t in fitted.fixed
    ]
    return columns, rows


def fixed_note(fitted: ml.Fitted, long: ml.Long) -> str:
    tested = (
        "df and p from Satterthwaite's method (lmerTest), as in JASP"
        if fitted.engine == ml.R
        else "p from z, since statsmodels has no Satterthwaite df; standard errors can differ "
        "from R's by a few percent"
    )
    parts = [f"Fitted by REML; {tested}; Wald 95% CIs."]
    if any(c.label.endswith(ml.PERSON_MEAN) for c in long.covariates):
        parts.append(
            "Each-wave number covariates are split into each person's mean over the chosen "
            "waves (the effect between people) and each wave's deviation from it (the effect "
            "within a person); JASP does not split them by itself."
        )
    parts += [f"{name}: compared with {level}." for name, level in ml.references(long)]
    return " ".join(parts)


def random_table(fitted: ml.Fitted) -> tuple[list[dict], list[dict]]:
    columns = [
        col("level", "Level", sortable=False),
        col("term", "Term", sortable=False),
        col("variance", "Variance", numeric=True),
        col("sd", "SD", numeric=True),
        col("r", "r", numeric=True),
    ]
    rows = [
        {
            "level": v.level,
            "term": v.term,
            "variance": decimal(v.variance),
            "sd": decimal(v.sd),
            "r": apa(v.correlation),
        }
        for v in fitted.random
    ]
    return columns, rows


def summary_table(fitted: ml.Fitted) -> tuple[list[dict], list[dict]]:
    columns = [col("measure", "", sortable=False), col("value", "Value", numeric=True)]
    rows = [{"measure": f"ICC, {level}", "value": apa(icc)} for level, icc in fitted.icc]
    rows += [
        {"measure": "Observations", "value": str(fitted.observations)},
        {"measure": "People", "value": str(fitted.people)},
        *(
            [{"measure": "Groups", "value": str(fitted.groups)}]
            if fitted.groups is not None
            else []
        ),
        {"measure": "REML criterion", "value": decimal(fitted.reml_criterion)},
        {"measure": "Log-likelihood (REML)", "value": decimal(fitted.log_likelihood)},
        *([{"measure": "AIC", "value": decimal(fitted.aic)}] if fitted.aic is not None else []),
        *([{"measure": "BIC", "value": decimal(fitted.bic)}] if fitted.bic is not None else []),
    ]
    return columns, rows


def summary_note(fitted: ml.Fitted) -> str:
    parts = [
        "ICC from the model with only the random intercepts: each level's share of the "
        "variance (performance::icc in R).",
        "Models fitted by REML cannot be compared on AIC or BIC when their fixed effects differ.",
    ]
    if fitted.left_out:
        parts.append(f"{fitted.left_out} rows left out for a missing or repeated ID.")
    if fitted.dropped:
        parts.append(f"{fitted.dropped} rows left out for a missing value.")
    return " ".join(parts)
