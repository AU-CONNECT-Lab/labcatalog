from pathlib import Path

from nicegui import app, ui

CSS = Path(__file__).with_name("theme.css")
CLEAR = "rgba(0,0,0,0)"
NAVY = "#1e2a3a"
OK = "#2f855a"
WARN = "#b7791f"
BAD = "#c05050"


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


def on_glass(figure: dict) -> dict:
    return {**figure, "layout": {**figure["layout"], "paper_bgcolor": CLEAR}}


def echart_on_glass(option: dict) -> dict:
    return {**option, "backgroundColor": CLEAR}
