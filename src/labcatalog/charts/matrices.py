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
MATRICES_PER_ROW = 3
# Data units left of and above the cells that hold the instrument strips.
STRIP_ROOM = 1.6


def as_matrix(rows: list[list[float | None]]) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in row] for row in rows], dtype=float)


def axis_refs(fig: go.Figure, row: int, col: int) -> dict:
    sub = fig.get_subplot(row, col)
    return dict(
        xref=sub.xaxis.plotly_name.replace("axis", ""),
        yref=sub.yaxis.plotly_name.replace("axis", ""),
    )


def dot_matrix(
    fig: go.Figure,
    z: np.ndarray,
    labels: list[str],
    *,
    row: int,
    col: int,
    value_label: str,
    n: list[list[int]] | None = None,
    groups: list[str] | None = None,
    group_order: list[str] | None = None,
    group_labels: dict[str, str] | None = None,
    row_labels: bool = True,
) -> tuple[list[dict], list[dict]]:
    # Dot area follows |r| and colour its sign; circles are shapes so they scale with the cells.
    size = len(labels)
    ref = axis_refs(fig, row, col)
    xs, ys = [], []
    for k in range(size + 1):
        xs += [k - 0.5, k - 0.5, None, -0.5, size - 0.5, None]
        ys += [-0.5, size - 0.5, None, k - 0.5, k - 0.5, None]
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            line=dict(color=CELL_LINE, width=0.6),
            hoverinfo="skip",
            showlegend=False,
        ),
        row=row,
        col=col,
    )
    shapes, notes, hx, hy, data = [], [], [], [], []
    for i in range(size):
        for j in range(size):
            value = z[i, j]
            if not np.isfinite(value):
                continue
            radius = 0.45 * np.sqrt(abs(value))
            shapes.append(
                dict(
                    type="circle",
                    x0=j - radius,
                    x1=j + radius,
                    y0=i - radius,
                    y1=i + radius,
                    fillcolor=scale_color(value, CORRELATION_SCALE, -1, 1),
                    line_width=0,
                    **ref,
                )
            )
            hx.append(j)
            hy.append(i)
            data.append([labels[i], labels[j], float(value), n[i][j] if n else ""])
    hover = "%{customdata[0]} × %{customdata[1]}<br>" + value_label + " = %{customdata[2]:.2f}"
    if n is not None:
        hover += "<br>n = %{customdata[3]}"
    fig.add_trace(
        go.Scatter(
            x=hx,
            y=hy,
            mode="markers",
            marker=dict(size=14, color="rgba(0,0,0,0)"),
            customdata=data,
            hovertemplate=hover + "<extra></extra>",
            showlegend=False,
        ),
        row=row,
        col=col,
    )
    low = -0.5
    if groups is not None:
        low = -STRIP_ROOM
        for i, g in enumerate(groups):
            color = group_color(group_order.index(g))
            for x0, x1, y0, y1 in (
                (-1.35, -0.65, i - 0.4, i + 0.4),
                (i - 0.4, i + 0.4, -1.35, -0.65),
            ):
                shapes.append(
                    dict(
                        type="rect",
                        x0=x0,
                        x1=x1,
                        y0=y0,
                        y1=y1,
                        fillcolor=color,
                        line_width=0,
                        **ref,
                    )
                )
        for g in dict.fromkeys(groups):
            start, end = groups.index(g), size - groups[::-1].index(g)
            notes.append(
                dict(
                    x=(start + end - 1) / 2,
                    y=-1.45,
                    yanchor="bottom",
                    text=f"<b>{group_labels[g]}</b>",
                    showarrow=False,
                    font=dict(size=10, color=group_color(group_order.index(g))),
                    **ref,
                )
            )
    ticks = dict(
        tickvals=list(range(size)),
        ticktext=labels,
        tickfont=dict(size=9, color=LABEL_INK),
        showgrid=False,
        zeroline=False,
        showline=False,
        ticks="",
    )
    fig.update_xaxes(
        row=row, col=col, range=[low, size - 0.5], tickangle=-90, constrain="domain", **ticks
    )
    fig.update_yaxes(
        row=row,
        col=col,
        range=[size - 0.5, low],
        scaleanchor=ref["xref"],
        scaleratio=1,
        constrain="domain",
        showticklabels=row_labels,
        automargin=True,
        **ticks,
    )
    return shapes, notes


def colorbar(title: str, plot_height: float) -> go.Scatter:
    # A horizontal bar above the top right corner of the panels.
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
                title=dict(text=title, side="top", font=dict(size=10)),
                orientation="h",
                thickness=8,
                len=0.22,
                x=1,
                xanchor="right",
                y=1 + 48 / plot_height,
                yanchor="bottom",
                tickvals=[-1, -0.5, 0, 0.5, 1],
                tickfont=dict(size=9),
                outlinewidth=0,
            ),
        ),
    )


def matrix_grid(titles: list[str], height_per_row: int) -> tuple[go.Figure, int, int, int]:
    cols = min(MATRICES_PER_ROW, len(titles))
    rows = -(-len(titles) // cols)
    height = 190 + height_per_row * rows
    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=titles,
        horizontal_spacing=0.06,
        vertical_spacing=130 / (height - 190) if rows > 1 else 0.0,
    )
    return fig, rows, cols, height


def finish_grid(fig: go.Figure, shapes: list, notes: list, height: int, title: str) -> go.Figure:
    fig.update_annotations(
        selector=dict(xref="paper"), font=dict(color=TITLE_INK, size=13), yshift=24
    )
    # Shapes and notes go in at once; adding hundreds one by one revalidates the layout each time.
    fig.update_layout(shapes=shapes, annotations=[*fig.layout.annotations, *notes])
    fig.add_trace(colorbar(title, height - 190))
    return base_layout(fig, height, margin=dict(l=110, r=16, t=110, b=80))


def item_correlations(panels: list[dict], value_label: str) -> go.Figure:
    fig, _, cols, height = matrix_grid([p["title"] for p in panels], 340)
    shapes, notes = [], []
    for k, panel in enumerate(panels):
        found = dot_matrix(
            fig,
            as_matrix(panel["r"]),
            panel["labels"],
            row=k // cols + 1,
            col=k % cols + 1,
            value_label=value_label,
            row_labels=k % cols == 0,
        )
        shapes += found[0]
        notes += found[1]
    return finish_grid(fig, shapes, notes, height, value_label)


def score_matrices(
    panels: list[dict], group_order: list[str], group_labels: dict[str, str]
) -> go.Figure:
    # Scores sit together by instrument; a colour strip on each side names the block.
    fig, _, cols, height = matrix_grid([p["title"] for p in panels], 380)
    shapes, notes = [], []
    for k, panel in enumerate(panels):
        found = dot_matrix(
            fig,
            as_matrix(panel["r"]),
            panel["short"],
            row=k // cols + 1,
            col=k % cols + 1,
            value_label="Pearson r",
            n=panel["n"],
            groups=panel["groups"],
            group_order=group_order,
            group_labels=group_labels,
            row_labels=k % cols == 0,
        )
        shapes += found[0]
        notes += found[1]
    return finish_grid(fig, shapes, notes, height, "Pearson r")


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
    group_labels: dict[str, str],
    skip: set[tuple[int, int]],
    threshold: float,
    title: str,
) -> go.Figure:
    # The matrix is the record (every pair); the circle shows which pairs are strong.
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
        subplot_titles=("", rule),
    )
    shapes, notes = dot_matrix(
        fig,
        z,
        labels,
        row=1,
        col=1,
        value_label="Pearson r",
        n=n,
        groups=groups,
        group_order=group_order,
        group_labels=group_labels,
    )

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
    height = 720
    fig.add_trace(colorbar("Pearson r", height - 150))
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", y=0.975, font=dict(size=14)),
        showlegend=False,
        xaxis2=dict(visible=False, range=[-CIRCLE_SPAN, CIRCLE_SPAN], constrain="domain"),
        yaxis2=dict(
            visible=False,
            range=[-CIRCLE_SPAN, CIRCLE_SPAN],
            scaleanchor="x2",
            scaleratio=1,
            constrain="domain",
        ),
    )
    fig.update_annotations(selector=dict(xref="paper"), font=dict(size=11, color="#444444"))
    fig.update_layout(shapes=shapes, annotations=[*fig.layout.annotations, *notes])
    return base_layout(fig, height, margin=dict(l=110, r=90, t=110, b=40))


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
