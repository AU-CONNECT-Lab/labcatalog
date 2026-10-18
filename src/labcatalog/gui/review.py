from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui.common import apa, col, empty, fmt, note, panel, table
from labcatalog.pipeline import CatalogResult

BAR_WIDTH = 6
BAR_HEIGHT = 22


@dataclass
class ScoreRow:
    label: str
    n: int
    mean: float | None
    sd: float | None
    alpha: float | None
    histogram: list[int] = field(default_factory=list)


@dataclass
class DatasetRow:
    dataset: str
    label: str
    rows: int
    ids: int
    # Of the answers the instruments ask for, how many the file has.
    answered: float | None
    missing_codes: int
    unexpected: int
    errors: int
    warnings: int
    scores: list[ScoreRow] = field(default_factory=list)


def review_rows(result: CatalogResult) -> list[DatasetRow]:
    summary = result.summary
    project = result.project
    by_key = {s.key: s for s in result.catalog.scores}
    found = []
    for d in summary.datasets:
        variables = [v for v in summary.variables if v.dataset == d.dataset]
        asked = sum(v.n_total for v in variables)
        issues = [i for i in result.report.issues if i.details.get("dataset") == d.dataset]
        row = DatasetRow(
            dataset=d.dataset,
            label=views.dataset_label(result, d.dataset),
            rows=d.n_rows,
            ids=d.n_ids,
            answered=sum(v.n_valid for v in variables) / asked if asked else None,
            missing_codes=sum(d.missing_totals.values()),
            unexpected=d.n_unexpected,
            errors=sum(i.level == "error" for i in issues),
            warnings=sum(i.level == "warning" for i in issues),
        )
        for s in summary.scores:
            if s.dataset != d.dataset:
                continue
            resolved = by_key[s.key]
            instrument = project.instruments[resolved.instrument_id]
            score = next(x for x in instrument.scores if x.id == resolved.score_id)
            row.scores.append(
                ScoreRow(
                    views.short_label(instrument, score),
                    s.n_valid,
                    s.mean,
                    s.sd,
                    s.alpha,
                    [count for _, _, count in s.histogram],
                )
            )
        found.append(row)
    return found


def bars(counts: list[int]) -> str:
    # A small histogram to spot a skewed or piled-up score at a glance.
    top = max(counts, default=0) or 1
    rects = "".join(
        f'<rect x="{i * BAR_WIDTH}" y="{BAR_HEIGHT - c / top * BAR_HEIGHT:.1f}" '
        f'width="{BAR_WIDTH - 1}" height="{c / top * BAR_HEIGHT:.1f}" fill="currentColor"/>'
        for i, c in enumerate(counts)
    )
    width = len(counts) * BAR_WIDTH
    return f'<svg width="{width}" height="{BAR_HEIGHT}" class="lc-bars">{rects}</svg>'


def render(result: CatalogResult, open_dataset: Callable[[str], None]) -> None:
    rows = review_rows(result)
    with panel("Review", "Each data file as the catalog reads it, before the analyses"):
        note(
            "How many of the answers each file should hold it has, how many are missing codes and "
            "how many are values the items do not allow, the problems found in it, and each "
            "score's spread. Open a file for its charts and its problems."
        )
        if not rows:
            empty("No data files read yet.")
            return
        for row in rows:
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes("w-full items-center gap-3"):
                    ui.label(row.label).classes("font-medium")
                    facts = [f"{row.rows} rows", f"{row.ids} IDs"]
                    if row.answered is not None:
                        facts.append(f"{row.answered:.0%} answered")
                    ui.label(", ".join(facts)).classes("lc-note")
                    if row.missing_codes:
                        ui.label(f"{row.missing_codes} missing codes").classes("lc-pill lc-info")
                    if row.unexpected:
                        ui.label(f"{row.unexpected} values not allowed").classes("lc-pill lc-warn")
                    if row.errors:
                        ui.label(f"{row.errors} errors").classes("lc-pill lc-bad")
                    if row.warnings:
                        ui.label(f"{row.warnings} warnings").classes("lc-pill lc-warn")
                    ui.space()
                    ui.button(
                        "Open", icon="open_in_new", on_click=lambda d=row.dataset: open_dataset(d)
                    ).props("flat dense no-caps")
                if row.scores:
                    score_table(row.scores)


def score_table(scores: list[ScoreRow]) -> None:
    columns = [
        col("score", "Score"),
        col("n", "n", numeric=True),
        col("m", "M (SD)", numeric=True),
        col("alpha", "α", numeric=True),
        col("shape", "Distribution", sortable=False),
    ]
    rows = [
        {
            "score": s.label,
            "n": s.n,
            "m": "" if s.mean is None else f"{fmt(s.mean)} ({fmt(s.sd)})",
            "alpha": apa(s.alpha),
            "shape": bars(s.histogram),
        }
        for s in scores
    ]
    shown = table(columns, rows)
    shown.add_slot(
        "body-cell-shape", '<q-td :props="props"><span v-html="props.value"></span></q-td>'
    )
