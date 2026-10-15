import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from labcatalog.charts.style import (
    CORRELATION_SCALE,
    LABEL_INK,
    STATUS_COLORS,
    STATUS_NAMES,
    TITLE_INK,
    base_layout,
    cell_values,
    group_color,
    scale_color,
)

CIRCLE_GAP = 12.0
CIRCLE_SPAN = 1.42


def as_matrix(rows: list[list[float | None]]) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in rows], dtype=float)


def lower_triangle(matrix: np.ndarray) -> np.ndarray:
    lower = matrix.copy()
    np.fill_diagonal(lower, np.nan)
    lower[np.triu_indices(len(lower), k=1)] = np.nan
    return lower


def correlation_bar(title: str, **extra) -> dict:
    return dict(
        title=dict(text=title, side="right", font=dict(size=10)),
        thickness=12,
        tickfont=dict(size=9),
        tickvals=[-1, -0.5, 0, 0.5, 1],
        **extra,
    )


def item_correlations(panels: list[dict], value_label: str) -> go.Figure:
    # One lower triangle per panel, all on one colour scale.
    fig = make_subplots(
        rows=1,
        cols=len(panels),
        horizontal_spacing=0.06,
        subplot_titles=[p["title"] for p in panels],
    )
    for c, panel in enumerate(panels, start=1):
        labels = panel["labels"]
        z = lower_triangle(as_matrix(panel["r"]))
        fig.add_trace(
            go.Heatmap(
                z=z,
                x=labels,
                y=labels,
                zmin=-1.0,
                zmax=1.0,
                colorscale=CORRELATION_SCALE,
                showscale=c == len(panels),
                colorbar=correlation_bar(value_label, len=0.8),
                hovertemplate="%{y}<br>%{x}<br>" + value_label + " = %{z:.3f}<extra></extra>",
            ),
            row=1,
            col=c,
        )
        cell_values(fig, z, labels, labels, scale=CORRELATION_SCALE, low=-1, high=1, row=1, col=c)
        fig.update_xaxes(
            tickangle=-90,
            tickfont=dict(size=9),
            showgrid=False,
            ticks="",
            constrain="domain",
            row=1,
            col=c,
        )
        fig.update_yaxes(
            autorange="reversed",
            scaleanchor=f"x{c if c > 1 else ''}",
            scaleratio=1,
            constrain="domain",
            tickfont=dict(size=9),
            showgrid=False,
            ticks="",
            row=1,
            col=c,
        )
    fig.update_annotations(font=dict(size=12, color=TITLE_INK))
    return base_layout(fig, 380, margin=dict(l=60, r=30, t=50, b=70))


def score_matrices(
    panels: list[dict], group_order: list[str], group_labels: dict[str, str]
) -> go.Figure:
    # Scores sit together by instrument; a colour strip names each block and a rule separates blocks.
    fig = make_subplots(
        rows=1,
        cols=len(panels),
        subplot_titles=[p["title"] for p in panels],
        horizontal_spacing=0.05,
    )
    for c, panel in enumerate(panels, start=1):
        groups = panel["groups"]
        n = len(groups)
        blocks = [(g, groups.index(g), n - groups[::-1].index(g)) for g in dict.fromkeys(groups)]
        z = as_matrix(panel["r"])
        np.fill_diagonal(z, np.nan)
        fig.add_trace(
            go.Heatmap(
                z=z,
                x=list(range(n)),
                y=list(range(n)),
                zmin=-1,
                zmax=1,
                colorscale=CORRELATION_SCALE,
                showscale=c == len(panels),
                customdata=[
                    [[panel["labels"][i], panel["labels"][j], panel["n"][i][j]] for j in range(n)]
                    for i in range(n)
                ],
                hovertemplate="%{customdata[0]} × %{customdata[1]}<br>r %{z:.2f} · n %{customdata[2]}<extra></extra>",
                colorbar=correlation_bar("Pearson r", len=0.8),
            ),
            row=1,
            col=c,
        )
        cell_values(
            fig,
            z,
            list(range(n)),
            list(range(n)),
            scale=CORRELATION_SCALE,
            low=-1,
            high=1,
            row=1,
            col=c,
        )
        axis = "" if c == 1 else str(c)
        for g, start, end in blocks:
            color = group_color(group_order.index(g))
            for x0, x1, y0, y1 in (
                (start - 0.5, end - 0.5, -1.1, -0.75),
                (-1.1, -0.75, start - 0.5, end - 0.5),
            ):
                fig.add_shape(
                    type="rect",
                    xref=f"x{axis}",
                    yref=f"y{axis}",
                    x0=x0,
                    x1=x1,
                    y0=y0,
                    y1=y1,
                    fillcolor=color,
                    line_width=0,
                )
            if start > 0:
                for x0, x1, y0, y1 in (
                    (start - 0.5, start - 0.5, -0.5, n - 0.5),
                    (-0.5, n - 0.5, start - 0.5, start - 0.5),
                ):
                    fig.add_shape(
                        type="line",
                        xref=f"x{axis}",
                        yref=f"y{axis}",
                        x0=x0,
                        x1=x1,
                        y0=y0,
                        y1=y1,
                        line=dict(color="black", width=0.8),
                        opacity=0.7,
                    )
            fig.add_annotation(
                xref=f"x{axis}",
                yref=f"y{axis}",
                x=(start + end - 1) / 2,
                y=-1.2,
                yanchor="bottom",
                text=f"<b>{group_labels[g]}</b>",
                showarrow=False,
                font=dict(size=11, color=color),
            )
        fig.update_xaxes(
            row=1,
            col=c,
            range=[-1.2, n - 0.5],
            tickvals=list(range(n)),
            ticktext=panel["short"],
            tickangle=-45,
            showgrid=False,
        )
        fig.update_yaxes(
            row=1,
            col=c,
            range=[n - 0.5, -1.6],
            tickvals=list(range(n)),
            ticktext=panel["short"],
            showgrid=False,
            showticklabels=c == 1,
        )
    fig.update_annotations(
        selector=dict(xref="paper"), font=dict(color=TITLE_INK, size=13), yshift=22
    )
    return base_layout(fig, 400, margin=dict(l=110, r=16, t=60, b=90))


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


def radial_label(fig, theta: float, radius: float, text: str, col: int) -> None:
    degrees = np.rad2deg(theta) % 360.0
    flip = 90.0 < degrees < 270.0
    fig.add_annotation(
        x=float(np.cos(theta) * radius),
        y=float(np.sin(theta) * radius),
        text=text,
        showarrow=False,
        font=dict(size=9, color=LABEL_INK),
        textangle=-(degrees - 180.0) if flip else -degrees,
        xanchor="right" if flip else "left",
        yanchor="middle",
        xref=f"x{col}",
        yref=f"y{col}",
    )


def score_circle(
    r: list[list[float | None]],
    n: list[list[int]],
    labels: list[str],
    groups: list[str],
    group_order: list[str],
    skip: set[tuple[int, int]],
    threshold: float,
    title: str,
) -> go.Figure:
    # The matrix is the record (every cell printed); the circle shows which pairs are strong.
    z = as_matrix(r)
    k = len(labels)
    keep = [
        (i, j)
        for i in range(k)
        for j in range(i)
        if (j, i) not in skip and np.isfinite(z[i, j]) and abs(z[i, j]) >= threshold
    ]
    rule = f"|Pearson r| ≥ {threshold:g} ({len(keep)} of {k * (k - 1) // 2})"
    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.5, 0.5],
        horizontal_spacing=0.03,
        subplot_titles=("Pearson r", rule),
    )
    lower = lower_triangle(z)
    fig.add_trace(
        go.Heatmap(
            z=lower,
            x=labels,
            y=labels,
            colorscale=CORRELATION_SCALE,
            zmin=-1,
            zmax=1,
            customdata=n,
            colorbar=correlation_bar("Pearson r", len=0.72, x=1.0, y=0.46),
            hovertemplate="%{y} × %{x}<br>Pearson r = %{z:.3f}<br>n = %{customdata}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    cell_values(fig, lower, labels, labels, scale=CORRELATION_SCALE, low=-1, high=1, row=1, col=1)

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
            ),
            row=1,
            col=2,
        )
        radial_label(fig, angles[i], 1.1, label, col=2)
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
            ),
            row=1,
            col=2,
        )
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor="center", y=0.975, font=dict(size=14)),
        showlegend=False,
        xaxis=dict(
            side="bottom",
            tickangle=-90,
            range=[-0.5, k - 0.5],
            showgrid=False,
            zeroline=False,
            constrain="domain",
        ),
        yaxis=dict(
            range=[k - 0.5, -0.5],
            showgrid=False,
            zeroline=False,
            scaleanchor="x",
            constrain="domain",
        ),
        xaxis2=dict(visible=False, range=[-CIRCLE_SPAN, CIRCLE_SPAN], constrain="domain"),
        yaxis2=dict(
            visible=False,
            range=[-CIRCLE_SPAN, CIRCLE_SPAN],
            scaleanchor="x2",
            scaleratio=1,
            constrain="domain",
        ),
    )
    for note in fig.layout.annotations[:2]:
        note.font.size = 11
        note.font.color = "#444444"
    return base_layout(fig, 720, margin=dict(l=70, r=90, t=80, b=70))


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
