import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from labcatalog.charts.style import (
    CELL_LINE,
    CORRELATION_SCALE,
    LABEL_INK,
    STATUS_COLORS,
    STATUS_NAMES,
    TITLE_INK,
    base_layout,
    group_color,
    scale_color,
)

CIRCLE_GAP = 12.0
CIRCLE_SPAN = 1.42
# Data units left of and above the cells that hold the group strips.
STRIP_ROOM = 1.1
# A dot of r = 1 spans this share of its cell, so the largest dots never touch the lines.
DOT_SPAN = 0.84
COLORBAR_TICKS = [-1, -0.6, -0.2, 0.2, 0.6, 1]


def as_matrix(rows: list[list[float | None]]) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in rows], dtype=float)


def colorbar(title: str, **where) -> go.Scatter:
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
                len=0.28,
                tickvals=COLORBAR_TICKS,
                tickfont=dict(size=10),
                outlinewidth=0,
                **where,
            ),
        ),
    )


def dot_grid(
    z: np.ndarray,
    n: list[list[int | None]],
    labels: list[str],
    groups: list[str] | None,
    group_order: list[str],
    group_names: dict[str, str],
    lower_name: str,
    upper_name: str,
    value_label: str,
) -> go.Figure:
    # A corrplot: one wave below the diagonal and one above, dot diameter and colour following r.
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
    shapes, hx, hy, data = [], [], [], []
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
            data.append([lower_name if i > j else upper_name, labels[i], labels[j], value, n[i][j]])
    fig.add_trace(
        go.Scatter(
            x=hx,
            y=hy,
            mode="markers",
            marker=dict(size=16, color="rgba(0,0,0,0)"),
            customdata=data,
            hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} × %{customdata[2]}<br>"
            + value_label
            + " = %{customdata[3]:.2f}<br>n = %{customdata[4]}<extra></extra>",
            showlegend=False,
        )
    )
    low = -0.5
    if groups is not None:
        low = -STRIP_ROOM
        for i, g in enumerate(groups):
            color = group_color(group_order.index(g))
            for x0, x1, y0, y1 in (
                (-1.0, -0.6, i - 0.46, i + 0.46),
                (i - 0.46, i + 0.46, -1.0, -0.6),
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
    key = (
        lower_name if lower_name == upper_name else f"◥ {upper_name} above<br>◣ {lower_name} below"
    )
    fig.add_annotation(
        x=low,
        y=low,
        xanchor="right",
        yanchor="bottom",
        align="right",
        text=key,
        showarrow=False,
        font=dict(size=11, color=TITLE_INK),
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
    fig.add_trace(colorbar(value_label, x=1, xanchor="right", y=-0.03, yanchor="top"))
    fig.update_layout(shapes=shapes)
    cell = float(np.clip(560 / size, 18, 40))
    return base_layout(
        fig,
        int(cell * (size + 1.6)) + 260,
        margin=dict(l=40, r=20, t=40, b=90),
        legend=dict(
            orientation="h",
            x=0,
            xanchor="left",
            y=-0.03,
            yanchor="top",
            bordercolor="#bbbbbb",
            borderwidth=1,
            font=dict(size=11),
        ),
    )


def ring_angles(counts: list[int], gap: float = CIRCLE_GAP, start: float = 90.0) -> np.ndarray:
    step = (360.0 - len(counts) * gap) / sum(counts)
    angles, k = [], 0
    for g, size in enumerate(counts):
        for _ in range(size):
            angles.append(start + gap / 2 + (k + 0.5) * step + g * gap)
            k += 1
    return np.deg2rad(angles)


def bezier(p0, p2, n: int = 40) -> tuple[np.ndarray, np.ndarray]:
    # Quadratic through the centre: how far a chord bows says how far apart its ends are.
    t = np.linspace(0.0, 1.0, n)[:, None]
    return tuple(((1 - t) ** 2 * np.asarray(p0) + t**2 * np.asarray(p2)).T)


def radial_label(fig, theta: float, radius: float, text: str) -> None:
    degrees = np.rad2deg(theta) % 360.0
    flip = 90.0 < degrees < 270.0
    fig.add_annotation(
        x=float(np.cos(theta) * radius),
        y=float(np.sin(theta) * radius),
        text=text,
        showarrow=False,
        font=dict(size=10, color=LABEL_INK),
        textangle=-(degrees - 180.0) if flip else -degrees,
        xanchor="right" if flip else "left",
        yanchor="middle",
    )


def score_circle(
    r: list[list[float | None]],
    labels: list[str],
    groups: list[str],
    group_order: list[str],
    skip: set[tuple[int, int]],
    threshold: float,
    title: str,
) -> go.Figure:
    # Only the strong pairs, as chords coloured by r; the dot grid above holds every pair.
    z = as_matrix(r)
    k = len(labels)
    keep = [
        (i, j)
        for i in range(k)
        for j in range(i)
        if (j, i) not in skip and np.isfinite(z[i, j]) and abs(z[i, j]) >= threshold
    ]
    fig = go.Figure()
    order = list(dict.fromkeys(groups))
    angles = ring_angles([groups.count(g) for g in order])
    xy = np.stack([np.cos(angles), np.sin(angles)], axis=1)
    half = (angles[1] - angles[0]) * 0.42 if k > 1 else np.deg2rad(8.0)
    for i, label in enumerate(labels):
        arc = np.linspace(angles[i] - half, angles[i] + half, 12)
        fig.add_trace(
            go.Scatter(
                x=np.cos(arc),
                y=np.sin(arc),
                mode="lines",
                line=dict(color=group_color(group_order.index(groups[i])), width=9),
                showlegend=False,
                hovertemplate=f"{label}<extra></extra>",
            )
        )
        radial_label(fig, angles[i], 1.1, label)
    for i, j in sorted(keep, key=lambda ij: abs(z[ij])):
        value = float(z[i, j])
        x, y = bezier(xy[i], xy[j])
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                mode="lines",
                line=dict(color=scale_color(value, CORRELATION_SCALE, -1, 1), width=1.6),
                showlegend=False,
                hovertemplate=f"{labels[i]} × {labels[j]}<br>Pearson r = {value:.3f}<extra></extra>",
            )
        )
    fig.add_trace(colorbar("Pearson r", x=1, xanchor="right", y=1, yanchor="bottom"))
    fig.update_layout(
        title=dict(
            text=f"{title}: |Pearson r| ≥ {threshold:g} ({len(keep)} of {k * (k - 1) // 2} pairs)",
            x=0.01,
            font=dict(size=12, color=TITLE_INK),
        ),
        showlegend=False,
        xaxis=dict(visible=False, range=[-CIRCLE_SPAN, CIRCLE_SPAN], constrain="domain"),
        yaxis=dict(
            visible=False,
            range=[-CIRCLE_SPAN, CIRCLE_SPAN],
            scaleanchor="x",
            scaleratio=1,
            constrain="domain",
        ),
    )
    return base_layout(fig, 640, margin=dict(l=20, r=20, t=70, b=20))


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
            range=[-0.5, len(strip) - 0.5],
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
        width=cell_size * min(len(people), per_row) + 200,
        margin=dict(t=50, b=50, l=50, r=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=10)),
    )
