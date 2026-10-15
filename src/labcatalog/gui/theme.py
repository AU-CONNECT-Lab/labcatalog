from pathlib import Path

from nicegui import app, ui

CSS = Path(__file__).with_name("theme.css")
CLEAR = "rgba(0,0,0,0)"
NAVY = "#1e2a3a"
OK = "#2f855a"
WARN = "#b7791f"
BAD = "#c05050"
MIN_FONT = 11


def install() -> None:
    app.colors(primary=NAVY, positive=OK, warning=WARN, negative=BAD)
    ui.add_css(CSS, shared=True)
    ui.button.default_props("unelevated rounded no-caps")
    ui.input.default_props("outlined dense")
    ui.select.default_props("outlined dense options-dense")
    ui.toggle.default_props(
        "rounded unelevated no-caps color=transparent text-color=grey-8"
        " toggle-color=white toggle-text-color=primary"
    )


def for_page(figure: dict) -> dict:
    layout = {**legible(figure["layout"]), "paper_bgcolor": CLEAR}
    return {**figure, "data": legible(figure["data"]), "layout": layout}


def legible(node):
    # Raises every font in a figure to at least MIN_FONT, leaving larger ones alone.
    if isinstance(node, list):
        return [legible(v) for v in node]
    if not isinstance(node, dict):
        return node
    out = {k: legible(v) for k, v in node.items()}
    for key, value in out.items():
        if key.endswith("font") and isinstance(value, dict):
            size = value.get("size")
            if isinstance(size, int | float) and size < MIN_FONT:
                out[key] = {**value, "size": MIN_FONT}
    return out


def echart_for_page(option: dict) -> dict:
    return {**option, "backgroundColor": CLEAR}
