import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from labcatalog.charts.style import (
    CORRELATION_SCALE,
    LABEL_INK,
    STATUS_COLORS,
    STATUS_NAMES,
    base_layout,
    group_color,
    scale_color,
)

COLORBAR_TICKS = [-1, -0.5, 0, 0.5, 1]
LABEL_CHAR = 5.4
# Column labels slant this way, so long names fit below narrow cells.
COLUMN_ANGLE = -45
MIN_CELL, MAX_CELL = 18, 40
# Pixels the cells share before they reach their minimum size.
CELL_ROOM = 360
# Few variables get larger cells, so the plot and the colour bar beside it stay this tall.
MIN_PLOT = 170
COLORBAR_ROOM = 90
STYLES = {"heatmap": "Heatmap", "dots": "Dots"}
CELL_LINE = "#d9d9d9"
# A dot of r = 1 spans this share of its cell, so the largest dots never touch the lines.
DOT_SPAN = 0.84
# Data units left of and above the cells that hold the group strips.
STRIP_ROOM = 0.95
DOT_TICKS = [-1, -0.6, -0.2, 0.2, 0.6, 1]
DOT_COLORBAR_LENGTH = 170


def as_matrix(rows: list[list[float | None]]) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in rows], dtype=float)


def drawable(labels: list[str]) -> bool:
    # One pair is a single number, which the table beside the chart already shows.
    return len(labels) >= 3


def heatmap(
    z: np.ndarray, labels: list[str], hover: list[list[str]], value_label: str
) -> go.Figure | None:
    if not drawable(labels):
        return None
    # The lower triangle, numbered like an APA table: rows from the second, columns to the second last.
    names = [f"{k}. {label}" for k, label in enumerate(labels, start=1)]
    rows, cols = range(1, len(labels)), range(len(labels) - 1)
    cell = max(MIN_PLOT / len(cols), min(MAX_CELL, max(MIN_CELL, CELL_ROOM / len(cols))))
    fig = go.Figure(
        go.Heatmap(
            z=[
                [float(z[i, j]) if j < i and np.isfinite(z[i, j]) else None for j in cols]
                for i in rows
            ],
            x=[names[j] for j in cols],
            y=[names[i] for i in rows],
            text=[[hover[i][j] if j < i else "" for j in cols] for i in rows],
            hovertemplate="%{text}<extra></extra>",
            hoverongaps=False,
            colorscale=CORRELATION_SCALE,
            zmin=-1,
            zmax=1,
            xgap=2,
            ygap=2,
            colorbar=dict(
                title=dict(text=value_label, font=dict(size=11)),
                thickness=12,
                tickvals=COLORBAR_TICKS,
                tickfont=dict(size=10),
                outlinewidth=0,
            ),
        )
    )
    ticks = dict(
        type="category",
        showgrid=False,
        zeroline=False,
        ticks="",
        tickfont=dict(size=11, color=LABEL_INK),
    )
    fig.update_xaxes(constrain="domain", tickangle=COLUMN_ANGLE, **ticks)
    fig.update_yaxes(
        autorange="reversed",
        scaleanchor="x",
        constrain="domain",
        constraintoward="top",
        automargin=True,
        **ticks,
    )
    left = int(LABEL_CHAR * max(len(names[i]) for i in rows)) + 16
    # A label at 45 degrees drops about 0.71 of its length.
    bottom = int(0.71 * LABEL_CHAR * max(len(names[j]) for j in cols)) + 24
    side = int(cell * len(cols))
    return base_layout(
        fig,
        side + 20 + bottom,
        width=left + side + COLORBAR_ROOM,
        margin=dict(l=left, r=COLORBAR_ROOM, t=20, b=bottom),
    )


def dot_colorbar(title: str, **where) -> go.Scatter:
    return go.Scatter(
        x=[None],
        y=[None],
        mode="markers",
        hoverinfo="skip",
        showlegend=False,
        marker=dict(
            colorscale=CORRELATION_SCALE,
            cmin=-1,
            cmax=1,
            color=[0],
            showscale=True,
            colorbar=dict(
                title=dict(text=title, side="top", font=dict(size=11)),
                orientation="h",
                thickness=10,
                lenmode="pixels",
                len=DOT_COLORBAR_LENGTH,
                tickvals=DOT_TICKS,
                tickfont=dict(size=10),
                outlinewidth=0,
                **where,
            ),
        ),
    )


def dot_matrix(
    z: np.ndarray,
    labels: list[str],
    hover: list[list[str]],
    groups: list[str],
    group_order: list[str],
    group_names: dict[str, str],
    value_label: str,
) -> go.Figure | None:
    # A corrplot of both sides of the diagonal, with a coloured strip per group along the edges.
    if not drawable(labels):
        return None
    size = len(labels)
    fig = go.Figure()
    xs, ys = [], []
    for k in range(size + 1):
        xs += [k - 0.5, k - 0.5, None, -0.5, size - 0.5, None]
        ys += [-0.5, size - 0.5, None, k - 0.5, k - 0.5, None]
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            line=dict(color=CELL_LINE, width=0.8),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    shapes, hx, hy, text = [], [], [], []
    for i in range(size):
        for j in range(size):
            value = z[i, j]
            if i == j or not np.isfinite(value):
                continue
            radius = DOT_SPAN / 2 * abs(value)
            shapes.append(
                dict(
                    type="circle",
                    xref="x",
                    yref="y",
                    x0=j - radius,
                    x1=j + radius,
                    y0=i - radius,
                    y1=i + radius,
                    fillcolor=scale_color(value, CORRELATION_SCALE, -1, 1),
                    line_width=0,
                )
            )
            hx.append(j)
            hy.append(i)
            text.append(hover[i][j])
    fig.add_trace(
        go.Scatter(
            x=hx,
            y=hy,
            mode="markers",
            marker=dict(size=16, color="rgba(0,0,0,0)"),
            text=text,
            hovertemplate="%{text}<extra></extra>",
            showlegend=False,
        )
    )
    low = -STRIP_ROOM
    for i, g in enumerate(groups):
        color = group_color(group_order.index(g))
        for x0, x1, y0, y1 in (
            (-0.85, -0.6, i - 0.46, i + 0.46),
            (i - 0.46, i + 0.46, -0.85, -0.6),
        ):
            shapes.append(
                dict(
                    type="rect",
                    xref="x",
                    yref="y",
                    x0=x0,
                    x1=x1,
                    y0=y0,
                    y1=y1,
                    fillcolor=color,
                    line_width=0,
                )
            )
    for g in dict.fromkeys(groups):
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name=group_names[g],
                marker=dict(symbol="square", size=12, color=group_color(group_order.index(g))),
            )
        )
    ticks = dict(
        tickvals=list(range(size)),
        ticktext=labels,
        tickfont=dict(size=11, color=LABEL_INK),
        showgrid=False,
        zeroline=False,
        showline=False,
        ticks="",
        automargin=True,
    )
    fig.update_xaxes(
        side="top", range=[low, size - 0.5], tickangle=-90, constrain="domain", **ticks
    )
    fig.update_yaxes(
        range=[size - 0.5, low], scaleanchor="x", scaleratio=1, constrain="domain", **ticks
    )
    fig.add_trace(dot_colorbar(value_label, x=1, xanchor="right", y=-0.03, yanchor="top"))
    fig.update_layout(shapes=shapes)
    # Row and column labels are the same, so one length sets the room left of and above the cells.
    label_px = LABEL_CHAR * max(len(label) for label in labels)
    left = int(max(100, label_px + 12))
    side = int(min(MAX_CELL, max(MIN_CELL, CELL_ROOM / size)) * (size - low + 0.5))
    # A legend placed on the whole figure only reserves room below the plot, not beside it.
    legend_rows = -(-len(set(groups)) // 3)
    return base_layout(
        fig,
        int(side + label_px + 60 + 76 + 24 * legend_rows),
        width=left + side + 20,
        margin=dict(l=left, r=20, t=40, b=76),
        legend=dict(
            orientation="h",
            x=0.01,
            xref="container",
            xanchor="left",
            y=0.01,
            yref="container",
            yanchor="bottom",
            bordercolor="#bbbbbb",
            borderwidth=1,
            font=dict(size=11),
        ),
    )


def answer_grid(
    cells: list[dict], item_labels: dict[str, str], per_row: int = 60, cell_size: int = 16
) -> go.Figure:
    # Items down, people across; long cohorts wrap into several strips of people.
    people = list(dict.fromkeys(c["person"] for c in cells))
    items = list(dict.fromkeys(c["item"] for c in cells))
    strips = [people[i : i + per_row] for i in range(0, len(people), per_row)]
    fig = make_subplots(
        rows=len(strips),
        cols=1,
        vertical_spacing=0.25 / max(1, len(strips) - 1) if len(strips) > 1 else 0.25,
        subplot_titles=[f"{s[0]} to {s[-1]}" for s in strips],
    )
    where = {
        person: (row, position)
        for row, strip in enumerate(strips, start=1)
        for position, person in enumerate(strip)
    }
    by_row: dict[int, list[dict]] = {}
    for cell in cells:
        by_row.setdefault(where[cell["person"]][0], []).append(cell)
    for row, members in by_row.items():
        fig.add_trace(
            go.Scatter(
                x=[where[c["person"]][1] for c in members],
                y=[items.index(c["item"]) for c in members],
                mode="markers",
                marker=dict(
                    symbol="square",
                    size=max(6, cell_size - 4),
                    color=[STATUS_COLORS[c["status"]] for c in members],
                    line=dict(width=0),
                ),
                text=[
                    f"Participant: {c['person']}<br>Item: {item_labels.get(c['item'], c['item'])}<br>Status: {c['text']}"
                    for c in members
                ],
                hovertemplate="%{text}<extra></extra>",
                showlegend=False,
            ),
            row=row,
            col=1,
        )
        strip = strips[row - 1]
        fig.update_xaxes(
            tickmode="array",
            tickvals=list(range(len(strip))),
            ticktext=strip,
            tickangle=45,
            showgrid=False,
            zeroline=False,
            # A short last strip keeps the column width of the full ones.
            range=[-0.5, len(strips[0]) - 0.5],
            row=row,
            col=1,
        )
        fig.update_yaxes(
            tickmode="array",
            tickvals=list(range(len(items))),
            ticktext=items,
            showgrid=False,
            zeroline=False,
            range=[-0.5, len(items) - 0.5],
            row=row,
            col=1,
        )
    for status in ("valid", "missing", "unexpected", "blank"):
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                name=STATUS_NAMES[status],
                marker=dict(
                    symbol="square",
                    size=10,
                    color=STATUS_COLORS[status],
                    line=dict(width=1, color="#bbb"),
                ),
            )
        )
    return base_layout(
        fig,
        (cell_size * len(items) + 100) * len(strips),
        margin=dict(t=50, b=50, l=50, r=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=10)),
    )
