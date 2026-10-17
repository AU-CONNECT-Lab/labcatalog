import base64
import json
import urllib.parse
from dataclasses import dataclass

import plotly.graph_objects as go
from nicegui import ui
from nicegui.events import GenericEventArguments

from labcatalog.gui import preferences
from labcatalog.gui.common import computed, note, open_path
from labcatalog.paths import portable_path
from labcatalog.pipeline import CatalogResult
from labcatalog.reports import outputs, tables
from labcatalog.reports.tables import PaperTable

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
) -> None:
    async def save() -> None:
        files = {}
        for paper_name, shown in (papers or {}).items():
            files |= tables.files(paper_name, shown)
        files |= {n: text.encode("utf-8") for n, text in (texts or {}).items()}
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

    with ui.row().classes("items-center gap-2"):
        ui.button("Save to outputs", icon="save", on_click=save).props(
            "flat dense no-caps"
        ).classes("lc-quiet-btn")
        saved = ui.row().classes("items-center gap-2")


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
