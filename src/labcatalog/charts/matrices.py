import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from labcatalog.charts.style import (
    CORRELATION_SCALE,
    LABEL_INK,
    STATUS_COLORS,
    STATUS_NAMES,
    base_layout,
)

COLORBAR_TICKS = [-1, -0.5, 0, 0.5, 1]
LABEL_CHAR = 5.8
MIN_CELL, MAX_CELL = 18, 40
# Pixels the cells share before they reach their minimum size.
CELL_ROOM = 360
# The plot is never shorter than this, so the colour bar keeps room for its ticks.
MIN_PLOT = 170
COLORBAR_ROOM = 90


def as_matrix(rows: list[list[float | None]]) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in rows], dtype=float)


def heatmap(
    z: np.ndarray, labels: list[str], hover: list[list[str]], value_label: str
) -> go.Figure:
    # The lower triangle, numbered like an APA table: rows from the second, columns to the second last.
    names = [f"{k}. {label}" for k, label in enumerate(labels, start=1)]
    rows, cols = range(1, len(labels)), range(len(labels) - 1)
    cell = int(min(MAX_CELL, max(MIN_CELL, CELL_ROOM / len(cols))))
    fig = go.Figure(
        go.Heatmap(
            z=[
                [float(z[i, j]) if j < i and np.isfinite(z[i, j]) else None for j in cols]
                for i in rows
            ],
            x=[str(j + 1) for j in cols],
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
                lenmode="pixels",
                len=MIN_PLOT,
                y=1,
                yanchor="top",
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
    fig.update_xaxes(constrain="domain", **ticks)
    fig.update_yaxes(
        autorange="reversed",
        scaleanchor="x",
        constrain="domain",
        constraintoward="top",
        automargin=True,
        **ticks,
    )
    left = int(LABEL_CHAR * max(len(names[i]) for i in rows)) + 16
    side = cell * len(cols)
    return base_layout(
        fig,
        max(side, MIN_PLOT) + 60,
        width=left + side + COLORBAR_ROOM,
        margin=dict(l=left, r=COLORBAR_ROOM, t=20, b=40),
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
