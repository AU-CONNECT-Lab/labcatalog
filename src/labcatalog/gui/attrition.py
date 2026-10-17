from collections.abc import Callable

from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui import paper
from labcatalog.gui.analysis import pick_menu
from labcatalog.gui.analysis_tables import INDENT, code_view, compute, decimal, later, section_files
from labcatalog.gui.common import col, fmt, note, p_value, panel
from labcatalog.pipeline import CatalogResult
from labcatalog.reports.measures import series
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis_script as script
from labcatalog.stats import attrition

SMALL = "†"
NOTE = (
    "M (SD) or n (%) on everyone with a value. {t_test}; Pearson's χ² without continuity "
    f"correction, as in JASP. {SMALL}Some expected counts are below 5."
)


def render(result: CatalogResult, view, study: str, wave: str) -> None:
    with panel("Attrition", "Those who returned at the next wave against those who did not"):
        second = attrition.next_wave(result, study, wave)
        if second is None:
            note("Pick an earlier wave above to compare those who returned with those who did not.")
            return
        names = attrition.wave_files(result, study, wave)
        choices = script.measures(result, names)
        if not choices:
            return
        view.attrition = [k for k in view.attrition if k in choices] or script.default_measures(
            result, names
        )

        @ui.refreshable
        def body() -> None:
            if not view.attrition:
                note("Pick at least one variable.")
                return

            async def fill() -> Callable:
                found_plan = attrition.plan(result, study, wave, view.attrition)
                if found_plan is None:
                    return lambda: note(
                        f"Fewer than two {attrition.unit(result)} either returned at Wave {second} "
                        "or did not."
                    )
                sample, frame, code = found_plan.sample, found_plan.frame, found_plan.code
                found, engine = await compute(result, sample, frame, code)
                texts = section_files(result, sample, frame, code)
                compared = attrition.read(found, found_plan.labels)
                text = sentence(found_plan, compared)
                shown = PaperTable(
                    f"Wave {wave} Characteristics of Those Who Did and Did Not Return at Wave {second}",
                    *attrition_table(found_plan, compared),
                    NOTE.format(t_test=attrition.T_TESTS[result.project.config.stats.t_test]),
                )

                def content() -> None:
                    ui.label(text).classes("lc-prose")
                    paper.copy_text(text)
                    paper.paper_table(shown)
                    paper.result_actions(
                        result,
                        f"attrition_{study}_w{wave}",
                        {"attrition": shown},
                        texts=texts,
                        engine=engine,
                    )
                    code_view(texts)

                return content

            later(fill)

        def choose(value: list[str] | None) -> None:
            view.attrition = value or []
            body.refresh()

        note(
            f"Wave {wave} values of the {attrition.unit(result)} who took part again at Wave "
            f"{second} against those who did not; anyone in any Wave {second} file counts as "
            "returned."
        )
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            chosen = (
                ui.select(
                    choices,
                    multiple=True,
                    value=view.attrition,
                    label="Variables",
                    with_input=True,
                    on_change=lambda e: choose(e.value),
                )
                .props("dense outlined use-chips")
                .classes("grow")
            )
            pick_menu(chosen, views.menu_groups(result, names, script.measures))
        body()


def statistic(test: attrition.Test) -> str:
    if test.test == "t":
        # Welch's df is fractional, Student's whole.
        df = f"{test.df:g}" if test.df.is_integer() else f"{test.df:.1f}"
        return f"t({df}) = {fmt(test.statistic)}"
    return f"χ²({test.df:g}) = {fmt(test.statistic)}" + (SMALL if test.small else "")


def p_text(p: float) -> str:
    shown = p_value(p)
    return f"p {shown}" if shown.startswith("<") else f"p = {shown}"


def attrition_table(
    found: attrition.Plan, compared: list[attrition.Compared]
) -> tuple[list[dict], list[dict]]:
    columns = [
        col("variable", "Variable", sortable=False),
        col("returned", f"Returned (n = {found.stayed})", numeric=True, sortable=False),
        col("left", f"Did not return (n = {found.left})", numeric=True, sortable=False),
        col("test", "Test", numeric=True, sortable=False),
        col("p", "p", numeric=True, sortable=False),
        col("d", "d", numeric=True, sortable=False),
    ]
    rows = []
    for c in compared:
        tested = (
            {
                "test": statistic(c.test),
                "p": p_value(c.test.p),
                "d": decimal(c.test.effect),
            }
            if c.test
            else {}
        )
        if len(c.rows) == 1 and not c.rows[0].level:
            r = c.rows[0]
            rows.append(
                {
                    "variable": c.label,
                    "returned": mean_sd(r.returned_mean, r.returned_sd),
                    "left": mean_sd(r.left_mean, r.left_sd),
                    **tested,
                }
            )
            continue
        rows.append({"variable": c.label, **tested})
        for r in c.rows:
            rows.append(
                {
                    "variable": f"{INDENT}{r.level}",
                    "returned": count(r.returned_n, r.returned_percent),
                    "left": count(r.left_n, r.left_percent),
                }
            )
    return columns, rows


def mean_sd(mean: float | None, sd: float | None) -> str:
    if mean is None:
        return ""
    return fmt(mean) + ("" if sd is None else f" ({fmt(sd)})")


def count(n: int, percent: float | None) -> str:
    return f"{n}" + ("" if percent is None else f" ({percent:.1f}%)")


def sentence(found: attrition.Plan, compared: list[attrition.Compared]) -> str:
    everyone = found.stayed + found.left
    text = (
        f"Of the {everyone} {found.unit} at Wave {found.first}, {found.left} "
        f"({round(100 * found.left / everyone)}%) did not take part at Wave {found.second}."
    )
    tested = [c for c in compared if c.test]
    same = [c.label for c in tested if c.test.p >= 0.05]
    differ = [f"{c.label} ({result_text(c.test)})" for c in tested if c.test.p < 0.05]
    if same:
        text += f" They did not differ from those who did in {series(same)}"
        text += f"; they differed in {series(differ)}." if differ else "."
    elif differ:
        text += f" They differed from those who did in {series(differ)}."
    return text


def result_text(test: attrition.Test) -> str:
    shown = f"{statistic(test).rstrip(SMALL)}, {p_text(test.p)}"
    return shown + (f", d = {fmt(test.effect)}" if test.effect is not None else "")
