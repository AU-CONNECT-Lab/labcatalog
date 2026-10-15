import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import gaussian_kde

from labcatalog.charts.style import LOLLIPOP_COLORS, TITLE_INK, base_layout, natural_key, rgba

FIT_COLOR = "#d62728"
INSET = dict(x0=0.50, x1=0.82, y0=0.03, y1=0.30)
RETEST_PER_ROW = 2


def regression(x_title: str, y_title: str, groups: list[dict]) -> go.Figure:
    # Points by group, one pooled fit, each group's density on the margins, residual boxes inset.
    fig = make_subplots(
        rows=2,
        cols=2,
        column_widths=[0.84, 0.16],
        row_heights=[0.16, 0.84],
        shared_xaxes=True,
        shared_yaxes=True,
        horizontal_spacing=0.008,
        vertical_spacing=0.008,
        specs=[[{}, None], [{}, {}]],
    )
    xs = np.concatenate([g["x"] for g in groups])
    ys = np.concatenate([g["y"] for g in groups])
    slope, intercept = np.polyfit(xs, ys, 1)
    for g in groups:
        fig.add_trace(
            go.Scatter(
                x=g["x"],
                y=g["y"],
                mode="markers",
                name=f"{g['name']} (N={len(g['x'])})",
                marker=dict(
                    size=9, color=g["color"], opacity=0.55, line=dict(width=0.6, color="white")
                ),
                customdata=g["ids"],
                hovertemplate="<b>%{customdata}</b><br>"
                + x_title
                + " %{x:.2f}<br>"
                + y_title
                + " %{y:.2f}<extra></extra>",
            ),
            row=2,
            col=1,
        )
    line = np.linspace(xs.min(), xs.max(), 50)
    fig.add_trace(
        go.Scatter(
            x=line,
            y=intercept + slope * line,
            mode="lines",
            line=dict(color=FIT_COLOR, width=3, dash="dash"),
            name=f"fit, r = {np.corrcoef(xs, ys)[0, 1]:.2f}",
            hoverinfo="skip",
        ),
        row=2,
        col=1,
    )
    grid_x = np.linspace(xs.min(), xs.max(), 200)
    grid_y = np.linspace(ys.min(), ys.max(), 200)
    for g in groups:
        if len(g["x"]) < 3 or np.ptp(g["x"]) == 0 or np.ptp(g["y"]) == 0:
            continue
        fill = rgba(g["color"], 0.3)
        fig.add_trace(
            go.Scatter(
                x=grid_x,
                y=gaussian_kde(g["x"])(grid_x),
                mode="lines",
                fill="tozeroy",
                fillcolor=fill,
                line=dict(color=g["color"], width=1.5),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=gaussian_kde(g["y"])(grid_y),
                y=grid_y,
                mode="lines",
                fill="tozerox",
                fillcolor=fill,
                line=dict(color=g["color"], width=1.5),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=2,
            col=2,
        )
    axis = dict(showline=True, linecolor="#222", ticks="outside")
    fig.update_xaxes(
        showgrid=True, griddash="dot", gridcolor="#cccccc", title_text=x_title, row=2, col=1, **axis
    )
    fig.update_yaxes(
        showgrid=True, griddash="dot", gridcolor="#cccccc", title_text=y_title, row=2, col=1, **axis
    )
    fig.update_xaxes(showline=True, linecolor="#222", showgrid=False, row=1, col=1)
    fig.update_yaxes(visible=False, row=1, col=1)
    fig.update_xaxes(visible=False, row=2, col=2)
    fig.update_yaxes(showgrid=False, row=2, col=2, **axis)
    residual_boxes(fig, [(g, g["y"] - (intercept + slope * g["x"])) for g in groups])
    return base_layout(
        fig,
        640,
        margin=dict(l=70, r=20, t=20, b=60),
        legend=dict(
            x=0.01,
            y=0.81,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#999",
            borderwidth=1,
            font=dict(size=13),
        ),
    )


def residual_boxes(fig: go.Figure, residuals: list[tuple[dict, np.ndarray]]) -> None:
    # Drawn as shapes so the inset covers the points behind it.
    low = min(float(v.min()) for _, v in residuals)
    high = max(float(v.max()) for _, v in residuals)
    pad = (high - low) * 0.05 or 1.0
    low, high = low - pad, high + pad
    width = INSET["x1"] - INSET["x0"] - 0.04

    def to_x(value: float) -> float:
        return INSET["x0"] + 0.02 + (value - low) / (high - low) * width

    def shape(kind: str, **where) -> None:
        fig.add_shape(type=kind, xref="paper", yref="paper", layer="above", **where)

    shape("rect", line=dict(color="#888", width=1.2), fillcolor="white", **INSET)
    fig.add_annotation(
        xref="paper",
        yref="paper",
        x=(INSET["x0"] + INSET["x1"]) / 2,
        y=INSET["y1"],
        yanchor="bottom",
        text="Residuals",
        showarrow=False,
        font=dict(size=12, color="#222"),
    )
    row_height = (INSET["y1"] - INSET["y0"] - 0.06) / len(residuals)
    ink = dict(color="#333", width=1)
    for k, (g, values) in enumerate(residuals):
        y = INSET["y1"] - 0.03 - (k + 0.5) * row_height
        h = row_height * 0.32
        q1, median, q3 = np.percentile(values, [25, 50, 75])
        reach = 1.5 * (q3 - q1)
        low_whisker = float(values[values >= q1 - reach].min())
        high_whisker = float(values[values <= q3 + reach].max())
        for a, b in ((low_whisker, q1), (q3, high_whisker)):
            shape("line", x0=to_x(a), x1=to_x(b), y0=y, y1=y, line=ink)
        for w in (low_whisker, high_whisker):
            shape("line", x0=to_x(w), x1=to_x(w), y0=y - h * 0.6, y1=y + h * 0.6, line=ink)
        shape("rect", x0=to_x(q1), x1=to_x(q3), y0=y - h, y1=y + h, fillcolor=g["color"], line=ink)
        shape(
            "line",
            x0=to_x(median),
            x1=to_x(median),
            y0=y - h,
            y1=y + h,
            line=dict(color="#333", width=1.5),
        )
        for value in values[(values < low_whisker) | (values > high_whisker)]:
            x = to_x(float(value))
            shape(
                "circle",
                x0=x - 0.003,
                x1=x + 0.003,
                y0=y - 0.006,
                y1=y + 0.006,
                line=dict(color="#333", width=0.8),
            )
    for tick in np.linspace(low, high, 5)[1:-1]:
        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=to_x(tick),
            y=INSET["y0"],
            yanchor="bottom",
            text=f"{tick:.1f}",
            showarrow=False,
            font=dict(size=10, color="#333"),
        )


def standardized(rows: list[dict]) -> go.Figure:
    # Every person's z on every score, a stem from zero, one colour per score.
    ordered = sorted(rows, key=lambda r: (r["variable"], natural_key(r["id"])))
    rng = np.random.default_rng(0)
    fig = go.Figure()
    for i, variable in enumerate(dict.fromkeys(r["variable"] for r in ordered)):
        color = LOLLIPOP_COLORS[i % len(LOLLIPOP_COLORS)]
        members = [(x, r) for x, r in enumerate(ordered, start=1) if r["variable"] == variable]
        xs = [x + rng.uniform(-0.15, 0.15) for x, _ in members]
        stem_x, stem_y = [], []
        for x, (_, r) in zip(xs, members, strict=True):
            stem_x += [x, x, None]
            stem_y += [0, r["z"], None]
        fig.add_trace(
            go.Scatter(
                x=stem_x,
                y=stem_y,
                mode="lines",
                line=dict(color=color, width=1),
                legendgroup=variable,
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=[r["z"] for _, r in members],
                mode="markers",
                marker=dict(size=8, color=color),
                name=variable,
                legendgroup=variable,
                customdata=[[r["id"], r["value"]] for _, r in members],
                hovertemplate="<b>%{customdata[0]}</b><br>"
                + variable
                + " %{customdata[1]:.2f}<br>z = %{y:.2f}<extra></extra>",
            )
        )
    fig.update_xaxes(title_text="Participants, grouped by score", showgrid=True, zeroline=True)
    fig.update_yaxes(title_text="Standardized value", showgrid=True, zeroline=True, zerolinewidth=2)
    fig.update_layout(template="plotly_white", hovermode="closest")
    base_layout(fig, 400, margin=dict(t=40, b=60, l=60, r=60))
    fig.update_layout(hoverlabel=dict(bgcolor="rgb(40, 40, 40)", font=dict(size=10, color="white")))
    return fig


def retest(panels: list[dict]) -> go.Figure:
    # One panel per score: each person's earlier score against their later one, the identity line dashed.
    cols = min(RETEST_PER_ROW, len(panels))
    rows = -(-len(panels) // cols)
    height = 90 + 270 * rows
    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=[p["title"] for p in panels],
        horizontal_spacing=0.14,
        vertical_spacing=80 / (height - 90) if rows > 1 else 0.0,
    )
    fig.update_annotations(font=dict(size=11, color=TITLE_INK))
    shown = set()
    rng = np.random.default_rng(0)
    for k, panel in enumerate(panels):
        row, col = k // cols + 1, k % cols + 1
        low, high = panel["range"]
        pad = (high - low) * 0.05 or 1.0
        fig.add_trace(
            go.Scatter(
                x=[low, high],
                y=[low, high],
                mode="lines",
                line=dict(color="#bbbbbb", width=1, dash="dash"),
                hoverinfo="skip",
                showlegend=False,
            ),
            row=row,
            col=col,
        )
        # Scores take few values; jitter of a quarter step keeps people from hiding behind each other.
        values = np.unique(np.concatenate([[*p["x"], *p["y"]] for p in panel["pairs"]]))
        step = float(np.diff(values).min()) if len(values) > 1 else high - low
        spread = min(0.25 * step, 0.03 * (high - low))
        for pair in panel["pairs"]:
            x, y = np.asarray(pair["x"], dtype=float), np.asarray(pair["y"], dtype=float)
            fig.add_trace(
                go.Scatter(
                    x=x + rng.uniform(-spread, spread, len(x)),
                    y=y + rng.uniform(-spread, spread, len(y)),
                    mode="markers",
                    name=pair["name"],
                    legendgroup=pair["name"],
                    showlegend=pair["name"] not in shown,
                    marker=dict(
                        size=7,
                        color=pair["color"],
                        opacity=0.55,
                        line=dict(width=0.5, color="white"),
                    ),
                    customdata=list(zip(pair["ids"], x, y, strict=True)),
                    hovertemplate=f"<b>%{{customdata[0]}}</b> · {pair['name']}"
                    "<br>earlier %{customdata[1]:.2f}, later %{customdata[2]:.2f}<extra></extra>",
                ),
                row=row,
                col=col,
            )
            shown.add(pair["name"])
        fig.add_annotation(
            x=0.02,
            xref=f"x{k + 1 if k else ''} domain",
            y=0.98,
            yref=f"y{k + 1 if k else ''} domain",
            xanchor="left",
            yanchor="top",
            align="left",
            showarrow=False,
            text="<br>".join(
                f"<span style='color:{p['color']}'>r = {p['r']:.2f} (n {p['n']})</span>"
                for p in panel["pairs"]
            ),
            font=dict(size=10),
            bgcolor="rgba(255,255,255,0.8)",
        )
        axis = dict(range=[low - pad, high + pad], gridcolor="#eeeeee", zeroline=False)
        fig.update_xaxes(
            title_text="Earlier wave" if row == rows else None, row=row, col=col, **axis
        )
        fig.update_yaxes(title_text="Later wave" if col == 1 else None, row=row, col=col, **axis)
    fig.update_xaxes(title_font=dict(size=10), tickfont=dict(size=9))
    fig.update_yaxes(title_font=dict(size=10), tickfont=dict(size=9))
    return base_layout(
        fig,
        height,
        margin=dict(l=60, r=20, t=70, b=50),
        legend=dict(
            orientation="h",
            x=0,
            y=1 + 40 / (height - 120),
            yanchor="bottom",
            font=dict(size=10),
        ),
    )
