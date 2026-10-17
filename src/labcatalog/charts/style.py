import re
from dataclasses import dataclass

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale


@dataclass(frozen=True)
class Palette:
    label: str
    waves: tuple[str, ...]
    groups: tuple[str, ...]
    pair: tuple[str, str]


def single(label: str, colors: tuple[str, ...]) -> Palette:
    return Palette(label, colors, colors, colors[:2])


PALETTES = {
    "default": Palette(
        "Default",
        waves=("#3498db", "#e67e22", "#34495e", "#9b59b6", "#2ecc71", "#e74c3c"),
        groups=("#8e44ad", "#e67e22", "#16a085", "#f39c12", "#2c3e50", "#1abc9c", "#c0392b"),
        pair=("#34495e", "#e67e22"),
    ),
    "okabe_ito": single(
        "Okabe-Ito", ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442")
    ),
    "nature": single(
        "Nature (NPG)",
        ("#E64B35", "#3C5488", "#00A087", "#F39B7F", "#4DBBD5", "#7E6148", "#8491B4"),
    ),
    "lancet": single(
        "Lancet", ("#00468B", "#ED0000", "#42B540", "#0099B4", "#925E9F", "#FDAF91", "#AD002A")
    ),
    "dataviz": single(
        "Dataviz", ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6")
    ),
}
DEFAULT_PALETTE = "default"
palette = DEFAULT_PALETTE
LOLLIPOP_COLORS = (
    "#A6CEE3",
    "#1F78B4",
    "#B2DF8A",
    "#33A02C",
    "#FB9A99",
    "#E31A1C",
    "#FDBF6F",
    "#FF7F00",
    "#CAB2D6",
    "#6A3D9A",
)
STATUS_COLORS = {
    "blank": "#D3D3D3",
    "unexpected": "#F8786E",
    "missing": "#FFD966",
    "valid": "#C5E0B3",
}
STATUS_NAMES = {
    "valid": "answered",
    "missing": "missing code",
    "unexpected": "not an option",
    "blank": "blank",
}
CORRELATION_SCALE = "RdBu_r"
SHARE_SCALE = "YlGnBu"
FONT = 'Segoe UI, -apple-system, BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif'
INK = "#1c2530"
TITLE_INK = "#34495e"
LABEL_INK = "#2c3e50"
MUTED_INK = "#9aa5af"
CONNECTOR = "#c3cad1"
GRID = "#f2f2f2"


def use_palette(name: str) -> None:
    global palette
    palette = name


def wave_color(index: int) -> str:
    waves = PALETTES[palette].waves
    return waves[index % len(waves)]


def group_color(index: int) -> str:
    groups = PALETTES[palette].groups
    return groups[index % len(groups)]


def pair_color(index: int) -> str:
    return PALETTES[palette].pair[index]


def base_layout(fig: go.Figure, height: int, **extra) -> go.Figure:
    fig.update_layout(
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family=FONT, color=INK),
        hoverlabel=dict(
            bgcolor="rgb(40, 40, 40)",
            bordercolor="rgb(40, 40, 40)",
            font=dict(family=FONT, size=11, color="white"),
        ),
        **extra,
    )
    return fig


def rgba(color: str, alpha: float) -> str:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def scale_color(value: float, scale: str, low: float, high: float) -> str:
    t = (float(value) - low) / ((high - low) or 1.0)
    return sample_colorscale(scale, [float(np.clip(t, 0.0, 1.0))])[0]


def natural_key(text: object) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(text))]


def smooth(shares: list[float], sigma: float) -> np.ndarray:
    # Display-only smoothing of binned counts; hover still reports the raw bins.
    index = np.arange(len(shares))
    weights = np.exp(-((index[:, None] - index[None, :]) ** 2) / (2 * sigma**2))
    return weights @ np.asarray(shares) / weights.sum(axis=1)
