from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape

from nicegui import ui

from labcatalog.charts import style, views
from labcatalog.config import dataset_by_name
from labcatalog.gui.common import apa, col, empty, fmt, note, panel, table
from labcatalog.pipeline import CatalogResult

PLOT_WIDTH = 120
PLOT_HEIGHT = 26


@dataclass
class WaveFacts:
    dataset: str
    wave: str
    color: str
    rows: int
    ids: int
    # Of the answers the instruments ask for, how many the file has.
    answered: float | None
    missing_codes: int
    unexpected: int
    errors: int
    warnings: int


@dataclass
class ScoreWave:
    n: int
    # Rows of the file with no score.
    missing: int
    rows: int
    mean: float | None
    sd: float | None
    alpha: float | None
    histogram: list[int] = field(default_factory=list)


@dataclass
class ScoreLine:
    label: str
    # One entry per wave of the group, in its order; None where the wave lacks the score.
    waves: list[ScoreWave | None]


@dataclass
class ReviewGroup:
    # The waves of one study's files from one reporter and modality, read side by side.
    title: str
    waves: list[WaveFacts]
    scores: list[ScoreLine]


def review_groups(result: CatalogResult) -> list[ReviewGroup]:
    config = result.project.config
    summary = result.summary
    by_key = {s.key: s for s in result.catalog.scores}
    summaries = {d.dataset: d for d in summary.datasets}
    keyed: dict[tuple[str, str, str], list[str]] = {}
    for name in summaries:
        d = dataset_by_name(config, name)
        keyed.setdefault((d.study, d.reporter, d.modality), []).append(name)
    groups = []
    for (study, reporter, modality), names in keyed.items():
        order = list(config.studies[study].waves)
        names.sort(
            key=lambda n: (
                order.index(w) if (w := dataset_by_name(config, n).wave) in order else len(order)
            )
        )
        waves = [facts(result, summaries[n], order) for n in names]
        lines: dict[tuple[str, str], ScoreLine] = {}
        for i, name in enumerate(names):
            rows = summaries[name].n_rows
            for s in summary.scores:
                if s.dataset != name:
                    continue
                resolved = by_key[s.key]
                place = (resolved.instrument_id, resolved.score_id)
                if place not in lines:
                    instrument = result.project.instruments[resolved.instrument_id]
                    score = next(x for x in instrument.scores if x.id == resolved.score_id)
                    lines[place] = ScoreLine(
                        views.short_label(instrument, score), [None] * len(names)
                    )
                lines[place].waves[i] = ScoreWave(
                    s.n_valid,
                    rows - s.n_valid,
                    rows,
                    s.mean,
                    s.sd,
                    s.alpha,
                    [count for _, _, count in s.histogram],
                )
        title = f"{config.studies[study].label or study} · {reporter} · {config.vocab.modality_label(modality)}"
        groups.append(ReviewGroup(title, waves, list(lines.values())))
    return groups


def facts(result: CatalogResult, d, order: list[str]) -> WaveFacts:
    config = result.project.config
    found = dataset_by_name(config, d.dataset)
    variables = [v for v in result.summary.variables if v.dataset == d.dataset]
    asked = sum(v.n_total for v in variables)
    issues = [i for i in result.report.issues if i.details.get("dataset") == d.dataset]
    index = order.index(found.wave) if found.wave in order else len(order)
    return WaveFacts(
        dataset=d.dataset,
        wave=views.wave_name(result, found.study, found.wave),
        color=style.wave_color(index),
        rows=d.n_rows,
        ids=d.n_ids,
        answered=sum(v.n_valid for v in variables) / asked if asked else None,
        missing_codes=sum(d.missing_totals.values()),
        unexpected=d.n_unexpected,
        errors=sum(i.level == "error" for i in issues),
        warnings=sum(i.level == "warning" for i in issues),
    )


def overlay(histograms: list[tuple[str, list[int]]]) -> str:
    # Each wave's histogram as a step line in its colour, on one scale, so the waves can be compared.
    drawn = [(color, counts) for color, counts in histograms if counts]
    if not drawn:
        return ""
    top = max((max(counts) for _, counts in drawn), default=0) or 1
    paths = []
    for color, counts in drawn:
        step = PLOT_WIDTH / len(counts)
        points = []
        for i, count in enumerate(counts):
            y = PLOT_HEIGHT - count / top * (PLOT_HEIGHT - 1)
            points += [f"{i * step:.1f},{y:.1f}", f"{(i + 1) * step:.1f},{y:.1f}"]
        paths.append(
            f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.5"/>'
        )
    return f'<svg width="{PLOT_WIDTH}" height="{PLOT_HEIGHT}">{"".join(paths)}</svg>'


def lines(values: list[tuple[str, str]]) -> str:
    # One line per wave, marked with the wave's colour.
    return "".join(
        f'<div><span style="color:{color}">●</span> {escape(text)}</div>' for color, text in values
    )


def render(result: CatalogResult, open_dataset: Callable[[str], None]) -> None:
    groups = review_groups(result)
    with panel("Review", "Each data file as the catalog reads it, before the analyses"):
        note(
            "The waves of one study's files from one reporter side by side: how many of the "
            "answers each file should hold it has, how many are missing codes and how many are "
            "values the items do not allow, the problems found in it, and each score's missing "
            "values and spread. Open a file for its charts and its problems."
        )
        if not groups:
            empty("No data files read yet.")
            return
        for group in groups:
            with ui.column().classes("w-full gap-1"):
                ui.label(group.title).classes("font-medium")
                for wave in group.waves:
                    wave_row(wave, open_dataset)
                if group.scores:
                    score_table(group)


def wave_row(wave: WaveFacts, open_dataset: Callable[[str], None]) -> None:
    with ui.row().classes("w-full items-center gap-3"):
        ui.html(f'<span style="color:{wave.color}">●</span>', sanitize=False)
        ui.label(f"{wave.wave} ({wave.dataset})")
        facts_text = [f"{wave.rows} rows", f"{wave.ids} IDs"]
        if wave.answered is not None:
            facts_text.append(f"{wave.answered:.0%} answered")
        ui.label(", ".join(facts_text)).classes("lc-note")
        if wave.missing_codes:
            ui.label(f"{wave.missing_codes} missing codes").classes("lc-pill lc-info")
        if wave.unexpected:
            ui.label(f"{wave.unexpected} values not allowed").classes("lc-pill lc-warn")
        if wave.errors:
            ui.label(f"{wave.errors} errors").classes("lc-pill lc-bad")
        if wave.warnings:
            ui.label(f"{wave.warnings} warnings").classes("lc-pill lc-warn")
        ui.space()
        ui.button(
            "Open", icon="open_in_new", on_click=lambda d=wave.dataset: open_dataset(d)
        ).props("flat dense no-caps")


def score_table(group: ReviewGroup) -> None:
    columns = [
        col("score", "Score"),
        col("n", "n", numeric=True, sortable=False),
        col("missing", "Missing", numeric=True, sortable=False),
        col("m", "M (SD)", numeric=True, sortable=False),
        col("alpha", "α", numeric=True, sortable=False),
        col("shape", "Distribution", sortable=False),
    ]
    rows = []
    for line in group.scores:
        held = [(w.color, s) for w, s in zip(group.waves, line.waves, strict=True) if s is not None]
        rows.append(
            {
                "score": line.label,
                "n": lines([(c, str(s.n)) for c, s in held]),
                "missing": lines(
                    [
                        (c, f"{s.missing} ({s.missing / s.rows:.0%})" if s.rows else "")
                        for c, s in held
                    ]
                ),
                "m": lines(
                    [(c, "" if s.mean is None else f"{fmt(s.mean)} ({fmt(s.sd)})") for c, s in held]
                ),
                "alpha": lines([(c, apa(s.alpha)) for c, s in held]),
                "shape": overlay([(c, s.histogram) for c, s in held]),
            }
        )
    shown = table(columns, rows)
    for name in ("n", "missing", "m", "alpha", "shape"):
        shown.add_slot(
            f"body-cell-{name}",
            '<q-td :props="props"><span v-html="props.value"></span></q-td>',
        )
