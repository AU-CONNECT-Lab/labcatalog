import re

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

WAVE_COLORS = ("#3498db", "#e67e22", "#34495e", "#9b59b6", "#2ecc71", "#e74c3c")
SERIES_COLORS = ("#34495e", "#e67e22")
GROUP_COLORS = ("#8e44ad", "#e67e22", "#16a085", "#f39c12", "#2c3e50", "#1abc9c", "#c0392b")
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
# Past this many rows the printed numbers no longer fit their cells; hover still shows them.
CELL_TEXT_MAX = 25
CORRELATION_SCALE = "RdBu_r"
SHARE_SCALE = "YlGnBu"
FONT = 'Segoe UI, -apple-system, BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif'
INK = "#1c2530"
TITLE_INK = "#34495e"
LABEL_INK = "#2c3e50"
MUTED_INK = "#9aa5af"
CONNECTOR = "#c3cad1"
GRID = "#f2f2f2"


def wave_color(index: int) -> str:
    return WAVE_COLORS[index % len(WAVE_COLORS)]


def group_color(index: int) -> str:
    return GROUP_COLORS[index % len(GROUP_COLORS)]


def base_layout(fig: go.Figure, height: int, **extra) -> go.Figure:
    fig.update_layout(
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family=FONT, color=INK),
        hoverlabel=dict(font=dict(family=FONT, size=11), bordercolor="#d8dee6"),
        **extra,
    )
    return fig


def rgba(color: str, alpha: float) -> str:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def scale_color(value: float, scale: str, low: float, high: float) -> str:
    t = (float(value) - low) / ((high - low) or 1.0)
    return sample_colorscale(scale, [float(np.clip(t, 0.0, 1.0))])[0]


def cell_values(fig, z, rows, cols, *, scale, low, high, row=None, col=None) -> None:
    # The ink follows each cell's own colour, so one rule serves every scale.
    if max(len(rows), len(cols)) > CELL_TEXT_MAX:
        return
    size = float(np.clip(150.0 / max(len(rows), len(cols), 1), 9.0, 13.0))
    groups: dict[str, list[list]] = {"white": [[], [], []], "#111111": [[], [], []]}
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            value = z[i][j]
            if value is None or not np.isfinite(value):
                continue
            rgb = scale_color(value, scale, low, high)
            red, green, blue = (float(x) for x in rgb[rgb.index("(") + 1 : -1].split(","))
            ink = "white" if 0.299 * red + 0.587 * green + 0.114 * blue < 140 else "#111111"
            xs, ys, texts = groups[ink]
            xs.append(c)
            ys.append(r)
            texts.append(f"{value:.2f}".replace("0.", "."))
    for ink, (xs, ys, texts) in groups.items():
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    text=texts,
                    mode="text",
                    hoverinfo="skip",
                    showlegend=False,
                    textfont=dict(size=size, color=ink),
                ),
                row=row,
                col=col,
            )


def natural_key(text: object) -> list:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(text))]


def smooth(shares: list[float], sigma: float) -> np.ndarray:
    # Display-only smoothing of binned counts; hover still reports the raw bins.
    index = np.arange(len(shares))
    weights = np.exp(-((index[:, None] - index[None, :]) ** 2) / (2 * sigma**2))
    return weights @ np.asarray(shares) / weights.sum(axis=1)
