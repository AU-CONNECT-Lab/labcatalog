import colorsys
import re
from pathlib import Path

from nicegui import app, ui

CSS = Path(__file__).with_name("theme.css")
CLEAR = "rgba(0,0,0,0)"
ACCENT = "#1d1d1f"
OK = "#1a7f37"
WARN = "#9a6700"
BAD = "#cf222e"
MIN_FONT = 11

LIGHT = "light"
DARK = "dark"
SYSTEM = "system"
APPEARANCES = {LIGHT: "Light", DARK: "Dark", SYSTEM: "Same as the system"}
DEFAULT_APPEARANCE = LIGHT
# Matches --lc-panel in dark mode, so a white plot area turns into the panel it sits on.
DARK_PANEL = (0x1F, 0x1F, 0x22)
# Below this spread between channels a color counts as grey: ink, grid lines, white.
NEUTRAL_CHROMA = 0.17
NAMED = {"white": (255, 255, 255), "black": (0, 0, 0), "gray": (128, 128, 128)}
NAMED |= {"grey": NAMED["gray"], "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211)}
RGBA = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")

dark = False  # Whether figures are drawn for a dark page; the window sets it.


def install() -> None:
    app.colors(primary=ACCENT, positive=OK, warning=WARN, negative=BAD)
    ui.add_css(CSS, shared=True)
    ui.button.default_props("unelevated no-caps")
    ui.input.default_props("outlined dense")
    ui.select.default_props("outlined dense options-dense")
    ui.toggle.default_props("flat no-caps toggle-color=primary")


def set_dark(on: bool) -> None:
    global dark
    dark = on


def mode_value(appearance: str) -> bool | None:
    # What ui.dark_mode takes: None follows the system.
    return {LIGHT: False, DARK: True}.get(appearance)


def codemirror_theme() -> str:
    return "oneDark" if dark else "basicLight"


def for_page(figure: dict) -> dict:
    layout = {**legible(figure["layout"]), "paper_bgcolor": CLEAR}
    figure = {**figure, "data": legible(figure["data"]), "layout": layout}
    if not dark:
        return figure
    figure = night(figure)
    return {**figure, "layout": {**figure["layout"], "plot_bgcolor": CLEAR}}


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
    option = night(option) if dark else option
    return {**option, "backgroundColor": CLEAR}


def night(node, colored: bool = False):
    # Flips the lightness of the greys under any key that names a color; hues stay as drawn.
    if isinstance(node, dict):
        return {k: night(v, colored or "color" in k.lower()) for k, v in node.items()}
    if isinstance(node, list | tuple):
        return [night(v, colored) for v in node]
    if colored and isinstance(node, str):
        return flipped(node)
    return node


def flipped(color: str) -> str:
    parsed = parse_color(color)
    if parsed is None:
        return color
    (r, g, b), alpha = parsed
    if (max(r, g, b) - min(r, g, b)) / 255 >= NEUTRAL_CHROMA:
        return color
    if (r, g, b) == (255, 255, 255):
        r, g, b = DARK_PANEL
    else:
        hue, lightness, saturation = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        lightness = 0.11 + (1 - lightness) * 0.82
        r, g, b = (round(c * 255) for c in colorsys.hls_to_rgb(hue, lightness, saturation))
    return f"rgba({r},{g},{b},{alpha:g})"


def parse_color(color: str) -> tuple[tuple[int, int, int], float] | None:
    text = color.strip().lower()
    if text in NAMED:
        return NAMED[text], 1.0
    if text.startswith("#") and len(text) in (4, 7, 9):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        try:
            channels = tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
            alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        except ValueError:
            return None
        return channels, alpha
    found = RGBA.fullmatch(text)
    if found is None:
        return None
    r, g, b, a = found.groups()
    return (round(float(r)), round(float(g)), round(float(b))), float(a) if a else 1.0
