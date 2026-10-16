from dataclasses import dataclass, field

from nicegui import ui

from labcatalog.charts import views
from labcatalog.gui import analysis_tables
from labcatalog.gui.analysis import sample_note
from labcatalog.gui.common import col, heading, note, section, sorted_waves, unique
from labcatalog.gui.datasets import methods_of, paragraphs
from labcatalog.gui.instruments import CFA_DONE, CFA_RUNNING, CFA_UNSET, CfaView, omegas
from labcatalog.gui.paper import copy_text, paper_table, save_button
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


def render(result: CatalogResult, view: MethodsView, cfa: CfaView) -> None:
    config = result.project.config
    studies = {
        name: study.label or name
        for name, study in config.studies.items()
        if any(d.study == name for d in config.datasets)
    }
    if not studies:
        note("No study has datasets yet.")
        return
    if view.study not in studies:
        view.study = next(iter(studies))

    @ui.refreshable
    def body() -> None:
        waves = sorted_waves(d.wave for d in config.datasets if d.study == view.study)
        if view.wave not in waves:
            view.wave = waves[0]
        if len(waves) > 1:
            with ui.row().classes("items-center gap-3"):
                ui.toggle(
                    {w: views.wave_name(result, view.study, w) for w in waves},
                    value=view.wave,
                    on_change=lambda e: choose_wave(e.value),
                ).props("dense no-caps")
                note("Table 1 and Measures describe this wave.")
        participants_part(result, view)
        procedure(result, view.study)
        section("Measures")
        measures_body(result, view, cfa)

    def choose_study(value: str) -> None:
        view.study, view.wave = value, None
        body.refresh()

    def choose_wave(value: str) -> None:
        view.wave = value
        body.refresh()

    if len(studies) > 1:
        ui.toggle(studies, value=view.study, on_change=lambda e: choose_study(e.value)).props(
            "no-caps"
        )
    body()


def participants_part(result: CatalogResult, view: MethodsView) -> None:
    study = view.study
    section("Participants")
    text = participants.paragraph(result.project, result.summary, study)
    ui.label(text).classes("max-w-4xl")
    copy_text(text)
    note(
        "Change the wording with participants: in labcatalog.yaml or in the study's file in "
        "studies/."
    )
    group = result.summary.group_name
    counted = (
        "n is the number of people with data from each reporter; returning are those also in "
        "the previous wave, with their share of that wave's n"
    )
    if group:
        counted += f"; {group} groups with data from any reporter, and with every reporter"
    shown = PaperTable("Participants by Wave", *retention_table(result, study), f"{counted}.")
    paper_table(shown)
    save_button(result, f"participants_{study}", {"participants": shown})
    datasets = [
        d.name for d in result.project.config.datasets if (d.study, d.wave) == (study, view.wave)
    ]
    sample = analysis.build_sample(result, datasets, intersect=False)
    sample_note(result, sample, "with data in this wave")
    analysis_tables.table_one_section(result, sample, view)


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


def procedure(result: CatalogResult, study: str) -> None:
    section("Procedure")
    found = methods_of(result, study)
    if not found:
        note(
            "Write how each modality's data were collected under methods: in the study's file in studies/."
        )
    for modality, text in found.items():
        heading(modality.capitalize())
        paragraphs(text)
        copy_text(" ".join(text.split()))


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
    if not used:
        note("No instruments in this wave.")
        return
    note(
        "Each instrument's paragraph with α and ω from that dataset; change the wording with "
        "measures: and description: as the instrument's page says."
    )
    if cfa.status == CFA_UNSET:
        note("Set the path to Rscript on the Settings page to add ω.")
    elif cfa.status == CFA_RUNNING:
        note("ω fills in when the factor models finish in R.")
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
            omegas(fits) if cfa.status == CFA_DONE else {},
        )
        texts.append(text)
        heading(f"{instrument.name} ({dataset})")
        ui.label(text).classes("max-w-4xl")
    copy_text("\n\n".join(texts))


def cfa_changed() -> None:
    measures_body.refresh()
