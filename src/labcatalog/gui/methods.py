from dataclasses import dataclass, field

from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui import analysis_tables, attrition
from labcatalog.gui.analysis import sample_text
from labcatalog.gui.common import (
    col,
    empty,
    note,
    page_head,
    panel,
    redraw,
    sorted_waves,
    unique,
)
from labcatalog.gui.datasets import paragraphs
from labcatalog.gui.instruments import CFA_DONE, CFA_RUNNING, CFA_UNSET, CfaView
from labcatalog.gui.paper import copy_text, paper_table, save_button
from labcatalog.metadata.studies import wave_methods
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import measures, participants
from labcatalog.reports.participants import wave_dates
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import analysis


@dataclass
class MethodsView:
    study: str | None = None
    wave: str | None = None
    measures: list[str] = field(default_factory=list)
    attrition: list[str] = field(default_factory=list)


def render(
    result: CatalogResult, view: MethodsView, cfa: CfaView, scope: str | None = None
) -> None:
    config = result.project.config
    studies = {
        name: study.label or name
        for name, study in config.studies.items()
        if scope in (None, name) and any(d.study == name for d in config.datasets)
    }
    if not studies:
        empty("This study has no datasets yet." if scope else "No study has datasets yet.")
        return
    if view.study not in studies:
        view.study = next(iter(studies))

    @ui.refreshable
    def body() -> None:
        waves = sorted_waves(d.wave for d in config.datasets if d.study == view.study)
        if view.wave not in waves:
            view.wave = waves[0]
        with page_head(
            "Methods",
            help_text="Text and tables for a paper's Methods section, for the chosen wave.",
        ):
            if len(studies) > 1:
                ui.toggle(
                    studies, value=view.study, on_change=lambda e: choose_study(e.value)
                ).props("dense no-caps")
            if len(waves) > 1:
                ui.toggle(
                    {w: views.wave_name(result, view.study, w) for w in waves},
                    value=view.wave,
                    on_change=lambda e: choose_wave(e.value),
                ).props("dense no-caps")
        participants_part(result, view)
        procedure(result, view.study, view.wave)
        measures_body(result, view, cfa)

    def choose_study(value: str) -> None:
        view.study, view.wave = value, None
        body.refresh()

    def choose_wave(value: str) -> None:
        view.wave = value
        body.refresh()

    body()


def participants_part(result: CatalogResult, view: MethodsView) -> None:
    study = view.study
    text = participants.paragraph(result.project, result.summary, study)
    with panel(
        "Participants",
        help_text="Change the wording with participants: in labcatalog.yaml or the study file.",
    ) as tools:
        ui.label(text).classes("lc-prose")
    with tools:
        copy_text(text)
    group = result.summary.group_name
    counted = (
        "n is the number of people with data from each reporter; returning are those also in "
        "the previous wave, with their share of that wave's n"
    )
    if group:
        counted += f"; {group} groups with data from any reporter, and with every reporter"
    shown = {
        "participants": PaperTable(
            "Participants by Wave", *retention_table(result, study), f"{counted}."
        )
    }
    if participants.modality_rows(result.summary, study):
        shown["modalities"] = PaperTable(
            "Participants by Modality",
            *modality_table(result, study),
            "n is the number of people in each modality's files at each wave, with their "
            "share of that wave's n for the same reporter; returning are those also in the "
            "last wave with this modality, with their share of it.",
        )
    with panel("Participants by wave", help_text="Who took part at each wave and who came back"):
        for table in shown.values():
            paper_table(table)
        with ui.row().classes("lc-actions w-full"):
            save_button(result, f"participants_{study}", shown)
    datasets = [
        d.name for d in result.project.config.datasets if (d.study, d.wave) == (study, view.wave)
    ]
    sample = analysis.build_sample(result, datasets, intersect=False)
    ui.label(sample_text(result, sample, "with data in this wave")).classes("lc-note px-1")
    analysis_tables.table_one_section(result, sample, view)
    attrition.render(result, view, study, view.wave)


def modality_table(result: CatalogResult, study: str) -> tuple[list[dict], list[dict]]:
    found = participants.modality_rows(result.summary, study)
    totals = participants.wave_totals(result.summary, study)
    several = len({reporter for _, reporter, _ in found}) > 1
    waves = sorted_waves(m.wave for _, _, counted in found for m in counted)
    columns = [col("modality", "Modality")]
    if several:
        columns.append(col("reporter", "Reporter"))
    returning = {
        m.wave for _, _, counted in found for m in counted if m.n_from_previous is not None
    }
    for i, w in enumerate(waves):
        columns.append(col(f"w{i}", f"Wave {w}", numeric=True))
        if w in returning:
            columns.append(col(f"back{i}", f"Wave {w} returning", numeric=True))
    vocab = result.project.config.vocab
    rows = []
    for modality, reporter, counted in found:
        row = {"modality": vocab.modality_label(modality), "reporter": reporter}
        for before, m in zip([None, *counted], counted, strict=False):
            i = waves.index(m.wave)
            total = totals[(m.wave, reporter)]
            row[f"w{i}"] = f"{m.n}{participants.share(m.n, total)}"
            if before is not None and m.n_from_previous is not None:
                row[f"back{i}"] = (
                    f"{m.n_from_previous}{participants.share(m.n_from_previous, before.n)}"
                )
        rows.append(row)
    return columns, rows


def retention_table(result: CatalogResult, study: str) -> tuple[list[dict], list[dict]]:
    summary = result.summary
    rows = [r for r in summary.retention if r.study == study]
    reporters = unique(r.reporter for r in rows)
    waves = sorted_waves(r.wave for r in rows)
    found = {(r.wave, r.reporter): r for r in rows}
    groups = {g.wave: g for g in summary.groups if g.study == study}
    group = summary.group_name
    columns = [col("wave", "Wave"), col("dates", "Dates", sortable=False)]
    for r in reporters:
        columns += [
            col(f"n_{r}", f"{r.capitalize()} n", numeric=True),
            col(f"back_{r}", f"{r.capitalize()} returning", numeric=True),
        ]
    if group:
        columns += [
            col("groups", f"{group.capitalize()} groups", numeric=True),
            col("complete", "With every reporter", numeric=True),
        ]
    waves_config = result.project.config.studies[study].waves
    table_rows = []
    for i, wave in enumerate(waves):
        row = {
            "wave": wave,
            "dates": wave_dates(waves_config[wave]) if wave in waves_config else "",
        }
        for r in reporters:
            now = found.get((wave, r))
            before = found.get((waves[i - 1], r)) if i else None
            row[f"n_{r}"] = now.n if now else ""
            row[f"back_{r}"] = (
                f"{now.n_from_previous} ({round(100 * now.n_from_previous / before.n)}%)"
                if now and before and before.n and now.n_from_previous is not None
                else ""
            )
        if wave in groups:
            row["groups"], row["complete"] = groups[wave].groups, groups[wave].with_every_reporter
        table_rows.append(row)
    return columns, table_rows


def procedure(result: CatalogResult, study: str, wave: str) -> None:
    found = wave_methods(result.project, study, wave)
    labels = result.project.config.vocab.modality_labels
    with panel("Procedure", help_text="How each modality's data were collected"):
        if not found:
            note(
                "Write how each modality's data were collected under methods: in the study's "
                "file in studies/; a dataset's name there gives that dataset its own text."
            )
        for modality, datasets, text in found:
            title = labels.get(modality, modality.capitalize())
            subhead(
                f"{title} ({', '.join(datasets)})" if datasets else title, " ".join(text.split())
            )
            paragraphs(text)


def subhead(title: str, text: str) -> None:
    with ui.row().classes("lc-subhead items-center no-wrap"):
        ui.label(title).classes("grow")
        copy_text(text)


# Module level, so a finished CFA can add ω without redrawing the page.
@ui.refreshable
def measures_body(result: CatalogResult, view: MethodsView, cfa: CfaView) -> None:
    config = result.project.config
    datasets = [d.name for d in config.datasets if (d.study, d.wave) == (view.study, view.wave)]
    used = unique(
        (v.instrument_id, v.dataset) for v in result.catalog.variables if v.dataset in datasets
    )
    order = list(result.project.instruments)
    used.sort(key=lambda pair: (order.index(pair[0]), datasets.index(pair[1])))
    with panel(
        "Measures",
        help_text="Each instrument's paragraph; change its wording on the instrument's page.",
    ) as tools:
        if not used:
            note("No instruments in this wave.")
            return
        if cfa.status in (CFA_UNSET, CFA_RUNNING):
            ui.label("ω fills in when the factor models finish.").classes("lc-status lc-info")
        texts = measure_paragraphs(result, used, cfa)
    with tools:
        copy_text("\n\n".join(texts))


def measure_paragraphs(
    result: CatalogResult, used: list[tuple[str, str]], cfa: CfaView
) -> list[str]:
    texts = []
    for instrument_id, dataset in used:
        instrument = result.project.instruments[instrument_id]
        fits = [f for f in cfa.fits if (f.instrument_id, f.dataset) == (instrument_id, dataset)]
        text = measures.paragraph(
            result.project,
            result.catalog,
            result.summary,
            instrument,
            dataset,
            fits if cfa.status == CFA_DONE else [],
        )
        texts.append(text)
        ui.label(f"{instrument.name} ({dataset})").classes("lc-subhead")
        ui.label(text).classes("lc-prose")
    return texts


def cfa_changed(cfa: CfaView) -> None:
    redraw(measures_body, cfa)
