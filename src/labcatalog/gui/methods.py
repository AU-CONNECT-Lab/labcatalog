from dataclasses import dataclass

from nicegui import ui

from labcatalog import measures
from labcatalog.charts import views
from labcatalog.gui import overview
from labcatalog.gui.common import heading, note, section, sorted_waves, unique
from labcatalog.gui.datasets import methods_of, paragraphs
from labcatalog.gui.instruments import CFA_DONE, CFA_RUNNING, CFA_UNSET, CfaView, omegas
from labcatalog.gui.paper import copy_text, paper_table, save_button
from labcatalog.pipeline import CatalogResult
from labcatalog.tables import PaperTable


@dataclass
class MethodsView:
    study: str | None = None
    wave: str | None = None


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
        participants(result, view.study)
        procedure(result, view.study)
        measures_part(result, view, cfa)

    def choose(value: str) -> None:
        view.study, view.wave = value, None
        body.refresh()

    if len(studies) > 1:
        ui.toggle(studies, value=view.study, on_change=lambda e: choose(e.value)).props("no-caps")
    body()


def participants(result: CatalogResult, study: str) -> None:
    section("Participants")
    columns, rows = overview.wave_table(result, study)
    group = result.summary.group_name
    counted = "n is the number of people with data from each reporter"
    if group:
        counted += f"; {group} groups with data from any reporter, and with every reporter"
    shown = PaperTable("Participants in Each Wave", columns, rows, f"{counted}.")
    paper_table(shown)
    save_button(result, f"participants_{study}", {"participants": shown})


def procedure(result: CatalogResult, study: str) -> None:
    section("Procedure")
    found = methods_of(result, study)
    if not found:
        note(
            f"Write how each modality's data were collected under methods: in studies/{study}.yaml."
        )
    for modality, text in found.items():
        heading(modality.capitalize())
        paragraphs(text)
        copy_text(" ".join(text.split()))


def measures_part(result: CatalogResult, view: MethodsView, cfa: CfaView) -> None:
    config = result.project.config
    waves = sorted_waves(d.wave for d in config.datasets if d.study == view.study)
    if view.wave not in waves:
        view.wave = waves[0]
    section("Measures")

    def choose(value: str) -> None:
        view.wave = value
        measures_body.refresh()

    if len(waves) > 1:
        ui.toggle(
            {w: views.wave_name(result, view.study, w) for w in waves},
            value=view.wave,
            on_change=lambda e: choose(e.value),
        ).props("dense no-caps")
    measures_body(result, view, cfa)


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
