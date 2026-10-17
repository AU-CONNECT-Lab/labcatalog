import base64
import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import plotly.graph_objects as go
from nicegui import ui
from nicegui.events import GenericEventArguments

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences
from labcatalog.gui.common import computed, note, open_path
from labcatalog.paths import portable_path
from labcatalog.pipeline import CatalogResult, run_interpretation
from labcatalog.reports import outputs, tables
from labcatalog.reports.tables import PaperTable
from labcatalog.stats import mplus

IMAGE_WIDTH = 900
IMAGE_KINDS = ("png", "svg")


@dataclass
class Chart:
    plot: ui.plotly | None = None
    fig: go.Figure | None = None


def paper_table(shown: PaperTable) -> None:
    ui.html(tables.html(shown, page=True), sanitize=False).classes("max-w-full overflow-x-auto")
    if wants_latex():
        copy_button("Copy as LaTeX", "Table", {"text/plain": tables.latex(shown)})
    else:
        kinds = {"text/html": tables.html(shown), "text/plain": tables.plain(shown)}
        copy_button("Copy table", "Table", kinds)


def results_text(text: str, shown: list[PaperTable] | None = None) -> None:
    if not text:
        return

    async def ask() -> None:
        button.disable()
        status.set_text("Asking the language model.")
        chosen = preferences.load()
        try:
            found = await computed(
                run_interpretation,
                shown,
                text,
                chosen.get(preferences.LLM_PROVIDER, preferences.DEFAULT_LLM_PROVIDER),
                chosen.get(preferences.LLM_MODEL, ""),
                chosen.get(preferences.LLM_URL, ""),
            )
        except LabCatalogError as err:
            status.set_text(str(err))
        else:
            meta = found.meta
            status.set_text(
                f"A draft by {meta.model} in {meta.latency_ms / 1000:.0f} s, {meta.input_tokens} "
                f"tokens in and {meta.output_tokens} out; check it against the tables."
            )
            answer.clear()
            with answer:
                ui.label(found.text).classes("lc-prose")
                copy_text(found.text)
                for line in found.notes:
                    note(f"To check: {line}")
        finally:
            button.enable()

    with ui.column().classes("w-full gap-1"):
        ui.label("Results paragraph").classes("lc-facet")
        ui.label(text).classes("lc-prose")
        with ui.row().classes("items-center gap-2"):
            copy_text(text)
            if shown and preferences.model_set():
                button = ui.button(
                    "Interpret with the language model", icon="psychology", on_click=ask
                ).props("flat dense no-caps")
                button.tooltip(
                    "Sends these tables and the paragraph, never any data, to the model set on "
                    "the Settings page."
                )
        status = ui.label().classes("lc-note")
        answer = ui.column().classes("w-full gap-1")


def copy_text(text: str) -> None:
    if wants_latex():
        copy_button("Copy as LaTeX", "Text", {"text/plain": tables.tex(text)})
    else:
        copy_button("Copy text", "Text", {"text/plain": text})


def wants_latex() -> bool:
    return preferences.load().get(preferences.TABLE_FORMAT) == preferences.LATEX


def copy_button(label: str, what: str, kinds: dict[str, str]) -> None:
    blobs = ", ".join(
        f"{json.dumps(kind)}: new Blob([{json.dumps(text)}], {{type: {json.dumps(kind)}}})"
        for kind, text in kinds.items()
    )
    # The browser lets a page write the clipboard only inside the click itself.
    copy = (
        f"() => navigator.clipboard.write([new ClipboardItem({{{blobs}}})])"
        ".then(() => emit('copied'), (error) => emit(String(error)))"
    )
    ui.button(label, icon="content_copy").props("flat dense no-caps").classes("lc-quiet-btn").on(
        "click", lambda event: copied(event, what), js_handler=copy
    )


def copied(event: GenericEventArguments, what: str) -> None:
    if event.args == "copied":
        ui.notify(f"{what} copied")
    else:
        ui.notify(f"Could not copy: {event.args}", type="warning")


def save_button(
    result: CatalogResult,
    name: str,
    papers: dict[str, PaperTable] | None = None,
    chart: Chart | None = None,
    texts: dict[str, str] | None = None,
    later_texts: Callable[[], dict[str, str]] | None = None,
) -> None:
    # later_texts builds files only when saving, such as Mplus inputs with their data.
    async def save() -> None:
        files = {}
        for paper_name, shown in (papers or {}).items():
            files |= tables.files(paper_name, shown)
        if later_texts is not None:
            texts_now = {**(texts or {}), **await computed(later_texts)}
        else:
            texts_now = texts or {}
        files |= {n: text.encode("utf-8") for n, text in texts_now.items()}
        if chart is not None and chart.plot is not None:
            for kind in IMAGE_KINDS:
                files[f"{name}.{kind}"] = await image(chart, kind)
        root = result.project.root
        folder = await computed(outputs.write_output, root, name, files, result.manifest)
        saved.clear()
        with saved:
            note(f"Saved to {portable_path(folder, root).as_posix()}")
            ui.button("Open folder", icon="folder_open", on_click=lambda: open_path(folder)).props(
                "flat dense no-caps"
            )
            if any(n.endswith(".inp") for n in files):
                mplus_button(folder)

    with ui.row().classes("items-center gap-2"):
        ui.button("Save to outputs", icon="save", on_click=save).props(
            "flat dense no-caps"
        ).classes("lc-quiet-btn")
        saved = ui.row().classes("items-center gap-2")


def mplus_button(folder: Path) -> None:
    program = preferences.load().get(preferences.MPLUS)
    if not program:
        return

    async def run() -> None:
        status.set_text("Running Mplus")
        try:
            found = await computed(mplus.run, program, folder)
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        status.set_text(f"Mplus wrote {len(found)} .out files beside the inputs.")

    ui.button("Run in Mplus", icon="play_arrow", on_click=run).props("flat dense no-caps")
    status = ui.label().classes("lc-note")


def result_actions(
    result: CatalogResult,
    name: str,
    papers: dict[str, PaperTable] | None = None,
    chart: Chart | None = None,
    texts: dict[str, str] | None = None,
    engine: str = "",
) -> None:
    # One line under a result: saving on the left, how it was computed on the right.
    with ui.row().classes("lc-actions w-full items-center gap-2"):
        save_button(result, name, papers, chart, texts)
        ui.space()
        ui.label(engine).classes("lc-engine")


def without_empty(
    columns: list[dict], rows: list[dict], name: str
) -> tuple[list[dict], list[dict]]:
    if any(row.get(name) for row in rows):
        return columns, rows
    return [c for c in columns if c["name"] != name], rows


async def image(chart: Chart, kind: str) -> bytes:
    options = {
        "format": kind,
        "width": chart.fig.layout.width or IMAGE_WIDTH,
        "height": chart.fig.layout.height,
        "scale": 2 if kind == "png" else 1,
    }
    # The page draws charts on a clear background, so the image comes from a copy with a white one.
    url = await ui.run_javascript(
        f"const plot = getElement({chart.plot.id});"
        "const figure = {data: plot.$el.data, layout: {...plot.$el.layout, paper_bgcolor: 'white'}};"
        f"return await plot.Plotly.toImage(figure, {json.dumps(options)});",
        timeout=20,
    )
    header, data = url.split(",", 1)
    return (
        base64.b64decode(data)
        if header.endswith(";base64")
        else urllib.parse.unquote(data).encode()
    )
