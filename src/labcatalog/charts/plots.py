from datetime import date, timedelta

import numpy as np
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from plotly.subplots import make_subplots

from labcatalog.charts.style import (
    CONNECTOR,
    GRID,
    MUTED_INK,
    SHARE_SCALE,
    TITLE_INK,
    base_layout,
    rgba,
    smooth,
)

BLOCK_GAP = 1.4
MEANS_PER_ROW = 4
RADARS_PER_ROW = 4
# Usual width of a full-width chart, for charts whose height follows their width.
PLOT_WIDTH = 900
RADAR_MAX_ROW = 420
ROW_HEIGHT = 24
ROW_LINE = "#ececec"
# Pixels above the rows for the title, the legend and the value axis.
DOT_TOP = 104
DOT_BOTTOM = 16
TITLE_ROOM = 28
# Room on the calendar before the first date and after the last.
TIMELINE_PAD = timedelta(days=30)
# Bar thickness as a share of a lane.
TIMELINE_BAR = 0.3
# Room beside the first and last wave, in waves.
TRAJECTORY_PAD = 0.12


def timeline(lanes: list[str], bars: list[dict], marks: list[dict], today: date) -> go.Figure:
    # One lane per wave and one per study's milestones on a shared calendar, today dashed across.
    fig = go.Figure()
    for bar in bars:
        pieces = [(bar["start"], bar["end"], 0.45 if bar["ongoing"] else 1.0)]
        if bar.get("projected"):
            pieces = [(bar["start"], bar["projected"], 0.25), (bar["start"], bar["end"], 1.0)]
        for start, end, alpha in pieces:
            fig.add_trace(
                go.Bar(
                    y=[bar["lane"]],
                    x=[(end - start).total_seconds() * 1000],
                    base=[start.isoformat()],
                    orientation="h",
                    width=TIMELINE_BAR,
                    marker=dict(color=rgba(bar["color"], alpha), line=dict(width=0)),
                    hovertext=[bar["hover"]],
                    hoverinfo="text",
                    showlegend=False,
                )
            )
        if bar.get("text"):
            # Above the bar from its start, where a long count cannot run off the calendar.
            fig.add_annotation(
                x=bar["start"].isoformat(),
                y=bar["lane"],
                yshift=8,
                xanchor="left",
                yanchor="bottom",
                text=bar["text"],
                showarrow=False,
                font=dict(size=10, color=TITLE_INK),
            )
    if marks:
        fig.add_trace(
            go.Scatter(
                x=[m["date"].isoformat() for m in marks],
                y=[m["lane"] for m in marks],
                mode="markers+text",
                text=[m["name"] for m in marks],
                textposition=label_sides(marks),
                textfont=dict(size=10, color=TITLE_INK),
                marker=dict(symbol="diamond", size=12, color=TITLE_INK),
                hovertext=[f"<b>{m['name']}</b><br>{m['date']:%Y-%m-%d}" for m in marks],
                hoverinfo="text",
                showlegend=False,
            )
        )
    fig.add_shape(
        type="line",
        x0=today.isoformat(),
        x1=today.isoformat(),
        y0=0,
        y1=1,
        yref="paper",
        line=dict(color=MUTED_INK, width=1.2, dash="dash"),
    )
    fig.add_annotation(
        x=today.isoformat(),
        y=1,
        yref="paper",
        yanchor="bottom",
        text="Today",
        showarrow=False,
        font=dict(size=10, color=MUTED_INK),
    )
    dates = [d for b in bars for d in (b["start"], b.get("projected") or b["end"])]
    dates += [m["date"] for m in marks] + [today]
    fig.update_xaxes(
        type="date",
        range=[
            (min(dates) - TIMELINE_PAD).isoformat(),
            (max(dates) + 2 * TIMELINE_PAD).isoformat(),
        ],
        gridcolor=GRID,
        tickfont=dict(size=10),
    )
    fig.update_yaxes(
        categoryorder="array",
        categoryarray=lanes,
        autorange="reversed",
        tickfont=dict(size=11),
        showgrid=False,
    )
    return base_layout(
        fig,
        70 + 46 * len(lanes),
        barmode="overlay",
        margin=dict(l=10, r=20, t=30, b=30),
    )


def label_sides(marks: list[dict]) -> list[str]:
    # Alternates above and below along each lane, so names of close dates do not collide.
    sides = {}
    for lane in {m["lane"] for m in marks}:
        ordered = sorted((m["date"], i) for i, m in enumerate(marks) if m["lane"] == lane)
        for k, (_, i) in enumerate(ordered):
            sides[i] = "top center" if k % 2 == 0 else "bottom center"
    return [sides[i] for i in range(len(marks))]


def score_boxes(title: str, labels: list[str], series: list[dict]) -> go.Figure:
    # One box per score and wave, every person a jittered point beside it.
    slot = 0.8 / max(len(series), 1)
    fig = go.Figure()
    for j, s in enumerate(series):
        offset = (j - (len(series) - 1) / 2) * slot
        box_x, box_y, pt_x, pt_y, meta = [], [], [], [], []
        for i, (values, ids) in s["values"].items():
            values = np.asarray(values, dtype=float)
            finite = np.isfinite(values)
            box_x += [i + offset] * int(finite.sum())
            box_y += values[finite].tolist()
            jitter = np.random.default_rng(j * 1000 + i).uniform(
                -slot * 0.22, slot * 0.22, len(values)
            )
            pt_x += (i + offset + jitter).tolist()
            pt_y += values.tolist()
            meta += [[pid, f"{s['name']} {labels[i]}"] for pid in ids]
        fig.add_trace(
            go.Box(
                x=box_x,
                y=box_y,
                width=slot * 0.68,
                boxpoints=False,
                boxmean=True,
                line=dict(color=s["color"], width=1.2),
                fillcolor="rgba(0,0,0,0)",
                hoverinfo="skip",
                showlegend=False,
                legendgroup=s["name"],
            )
        )
        fig.add_trace(
            go.Scatter(
                x=pt_x,
                y=pt_y,
                mode="markers",
                name=s["name"],
                legendgroup=s["name"],
                marker=dict(
                    color=s["color"], size=7, opacity=0.85, line=dict(width=0.5, color="#2c3e50")
                ),
                customdata=meta,
                hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]} = %{y:.4g}<extra></extra>",
                showlegend=len(series) > 1,
            )
        )
    k = len(labels)
    fig.update_xaxes(
        tickvals=list(range(k)),
        ticktext=labels,
        range=[-0.6, k - 0.4],
        tickangle=-30 if k > 1 else 0,
        gridcolor=GRID,
    )
    fig.update_yaxes(gridcolor="#eeeeee", zeroline=False)
    return base_layout(
        fig,
        340,
        title=dict(text=title, x=0.02, xanchor="left", font=dict(size=12)),
        margin=dict(l=58, r=14, t=34, b=70),
        boxmode="overlay",
        legend=dict(
            orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0, font=dict(size=10)
        ),
    )


def score_ridges(title: str, rows: list[dict], integer: bool) -> go.Figure:
    # Ridges share one height scale, so a wave with fewer people still reads as a distribution.
    curves = []
    for row in rows:
        total = max(sum(count for *_, count in row["histogram"]), 1)
        shares = [count / total for *_, count in row["histogram"]]
        curves.append(smooth(shares, 0.9 if integer else 1.4))
    peak = max(curve.max() for curve in curves) or 1.0
    low, high = rows[0]["possible_range"]
    fig = go.Figure()
    for i, (row, curve) in enumerate(zip(rows, curves, strict=True)):
        base = len(rows) - 1 - i
        bins = row["histogram"]
        xs = [bins[0][0], *[(a + b) / 2 for a, b, _ in bins], bins[-1][1]]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=[base] * len(xs),
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=[base, *(base + 0.8 * curve / peak), base],
                mode="lines",
                fill="tonexty",
                fillcolor=rgba(row["color"], 0.28),
                line=dict(color=row["color"], width=1.8, shape="spline", smoothing=0.8),
                showlegend=False,
                customdata=[[None, None], *[[a, c] for a, _, c in bins], [None, None]],
                hovertemplate=f"{row['label']}<br>score %{{customdata[0]:.3~g}}: %{{customdata[1]}} people<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[row["mean"]],
                y=[base - 0.13],
                mode="markers",
                showlegend=False,
                marker=dict(size=9, color=row["color"], line=dict(color="white", width=1)),
                hovertemplate=f"<b>{row['label']}</b><br>n {row['n']} · mean %{{x:.2f}}<extra></extra>",
            )
        )
    pad = (high - low) * 0.03
    fig.update_xaxes(range=[low - pad, high + pad], title_text=title, gridcolor=GRID)
    fig.update_yaxes(
        tickvals=[len(rows) - 1 - i for i in range(len(rows))],
        ticktext=[
            f"{r['label']}<br><span style='font-size:11px;color:{MUTED_INK}'>n {r['n']}</span>"
            for r in rows
        ],
        showgrid=False,
        range=[-0.35, len(rows) - 0.05],
    )
    return base_layout(fig, 90 + 80 * len(rows), margin=dict(l=84, r=16, t=16, b=48))


def response_bars(options: list[tuple[str, str]], rows: list[dict]) -> go.Figure:
    # One 100% bar per item and wave, answers coloured from low to high.
    colors = sample_colorscale(SHARE_SCALE, list(np.linspace(0.15, 0.9, len(options))))
    labels = [row["label"] for row in rows]
    fig = go.Figure()
    for (value, name), color in zip(options, colors, strict=True):
        shares, meta = [], []
        for row in rows:
            total = sum(row["counts"].get(v, 0) for v, _ in options) or 1
            shares.append(100 * row["counts"].get(value, 0) / total)
            meta.append([row["text"], row["counts"].get(value, 0), total])
        fig.add_trace(
            go.Bar(
                x=shares,
                y=labels,
                orientation="h",
                name=name,
                customdata=meta,
                marker=dict(color=color, line=dict(width=0.5, color="#fff")),
                hovertemplate=f"<b>%{{y}}</b> %{{customdata[0]}}<br>{name}: %{{x:.1f}}% (%{{customdata[1]}} of %{{customdata[2]}})<extra></extra>",
            )
        )
    fig.update_xaxes(
        title_text="Share of valid answers",
        title_font=dict(size=10),
        ticksuffix="%",
        range=[0, 100],
        dtick=25,
        gridcolor="#f5f5f5",
        tickfont=dict(size=9),
        zeroline=False,
    )
    fig.update_yaxes(tickfont=dict(size=9), showgrid=False, autorange="reversed")
    return base_layout(
        fig,
        110 + 24 * len(rows),
        barmode="stack",
        bargap=0.3,
        margin=dict(l=110, r=24, t=52, b=46),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=10),
            traceorder="normal",
        ),
    )


def block_positions(blocks: list[tuple[str, list[dict]]]) -> tuple[list[dict], np.ndarray, list]:
    members, xs, spans, x = [], [], [], 0.0
    for label, block in blocks:
        start = x
        for member in block:
            members.append(member)
            xs.append(x)
            x += 1.0
        spans.append((start, x - 1.0, label))
        x += BLOCK_GAP
    return members, np.asarray(xs, dtype=float), spans


def dot_rows(
    blocks: list[tuple[str, list[dict]]],
    series: list[dict],
    label: str,
    title: str,
    value_range: tuple[float, float] | None = None,
    value_format: str = ".2f",
) -> go.Figure:
    # A row per member with a dot per series, the dots of one row joined; named blocks get a heading.
    members, ys, spans = block_positions([b for b in blocks if b[1]])
    headed = any(name for *_, name in spans)
    fig = go.Figure()
    seg_x, seg_y = [], []
    for y, member in zip(ys, members, strict=True):
        values = [s["values"].get(member["id"]) for s in series]
        values = [v for v in values if v is not None and np.isfinite(v)]
        if len(values) > 1:
            seg_x += [min(values), max(values), None]
            seg_y += [y, y, None]
    fig.add_trace(
        go.Scatter(
            x=seg_x,
            y=seg_y,
            mode="lines",
            hoverinfo="skip",
            line=dict(color=CONNECTOR, width=2),
            showlegend=False,
        )
    )
    measured = []
    for s in series:
        x = np.array(
            [np.nan if s["values"].get(m["id"]) is None else s["values"][m["id"]] for m in members],
            dtype=float,
        )
        ok = np.isfinite(x)
        measured.append(x[ok])
        notes = s.get("notes", {})
        fig.add_trace(
            go.Scatter(
                x=x[ok],
                y=ys[ok],
                mode="markers",
                name=s["name"],
                customdata=[
                    [members[i]["hover"], notes.get(members[i]["id"], "")]
                    for i in np.flatnonzero(ok)
                ],
                marker=dict(size=9, color=s["color"], line=dict(width=0.8, color="white")),
                hovertemplate=f"<b>{s['name']}</b><br>%{{customdata[0]}}<br>{label} = "
                f"%{{x:{value_format}}}%{{customdata[1]}}<extra></extra>",
            )
        )
    if value_range is None:
        values = np.concatenate(measured) if any(len(m) for m in measured) else np.zeros(1)
        low, high = float(values.min()), float(values.max())
        pad = 0.06 * ((high - low) or abs(high) or 1.0)
        value_range = (low - pad, high + pad)
    for start, _, name in spans:
        if name:
            fig.add_annotation(
                x=0,
                xref="x domain",
                y=start - 0.95,
                xanchor="left",
                text=f"<b>{name}</b>",
                showarrow=False,
                font=dict(size=10, color=TITLE_INK),
            )
    fig.update_xaxes(
        title_text=label,
        title_font=dict(size=10),
        side="top",
        range=list(value_range),
        tickformat=value_format,
        gridcolor=GRID,
        tickfont=dict(size=9),
        zeroline=False,
    )
    top = -1.6 if headed else -0.7
    fig.update_yaxes(
        tickmode="array",
        tickvals=ys,
        ticktext=[m["tick"] for m in members],
        tickfont=dict(size=10),
        range=[ys[-1] + 0.7, top],
        gridcolor=ROW_LINE,
        zeroline=False,
        automargin=True,
    )
    above = DOT_TOP if title else DOT_TOP - TITLE_ROOM
    height = above + DOT_BOTTOM + int(ROW_HEIGHT * (ys[-1] + 0.7 - top))
    return base_layout(
        fig,
        height,
        margin=dict(l=10, r=24, t=above, b=DOT_BOTTOM),
        title=dict(
            text=title,
            x=0.01,
            y=1,
            yref="container",
            yanchor="top",
            pad=dict(t=10),
            font=dict(size=13, color=TITLE_INK),
        ),
        legend=dict(
            orientation="h",
            x=0,
            y=1 - ((TITLE_ROOM if title else 0) + 6) / height,
            yref="container",
            yanchor="top",
            font=dict(size=10),
        ),
    )


def radar_grid(panels: list[dict], value_range: tuple[float, float]) -> go.Figure:
    # One radar per panel side by side, every series on each.
    cols = min(RADARS_PER_ROW, len(panels))
    rows = -(-len(panels) // cols)
    row_height = min(RADAR_MAX_ROW, PLOT_WIDTH // cols + 60)
    height = 80 + row_height * rows
    fig = make_subplots(
        rows=rows,
        cols=cols,
        specs=[[{"type": "polar"}] * cols for _ in range(rows)],
        subplot_titles=[p["title"] for p in panels],
        horizontal_spacing=0.1,
        vertical_spacing=90 / (height - 80) if rows > 1 else 0.0,
    )
    shown = set()
    for k, panel in enumerate(panels):
        axes, hovers = panel["axes"], panel["hovers"]
        for s in panel["series"]:
            values = [s["values"].get(axis) for axis in axes]
            fig.add_trace(
                go.Scatterpolar(
                    r=values + values[:1],
                    theta=axes + axes[:1],
                    name=s["name"],
                    legendgroup=s["name"],
                    showlegend=s["name"] not in shown,
                    mode="lines+markers",
                    fill="toself",
                    fillcolor=rgba(s["color"], 0.12),
                    line=dict(color=s["color"], width=2),
                    marker=dict(size=6, color=s["color"]),
                    customdata=hovers + hovers[:1],
                    hovertemplate=f"<b>{s['name']}</b><br>%{{customdata}}<br>mean %{{r:.2f}}<extra></extra>",
                ),
                row=k // cols + 1,
                col=k % cols + 1,
            )
            shown.add(s["name"])
        fig.layout[f"polar{k + 1 if k else ''}"].update(
            bgcolor="white",
            radialaxis=dict(
                range=list(value_range),
                gridcolor="#eef0f3",
                linecolor="#d8dee6",
                tickfont=dict(color="#6c7684", size=9),
                angle=90 + 180 / len(axes),
                tickangle=0,
            ),
            angularaxis=dict(
                gridcolor="#eef0f3",
                linecolor="#d8dee6",
                direction="clockwise",
                rotation=90,
                tickfont=dict(size=10),
            ),
        )
    fig.update_annotations(font=dict(size=12, color=TITLE_INK), yshift=28)
    return base_layout(
        fig,
        height,
        margin=dict(l=48, r=48, t=70, b=40),
        legend=dict(orientation="h", x=0, y=-0.02, yanchor="top"),
    )


def score_means(panels: list[dict], wave_labels: list[str]) -> go.Figure:
    # Each score keeps its own y scale; sharing one would flatten the narrow-range scores.
    cols = min(MEANS_PER_ROW, len(panels))
    rows = -(-len(panels) // cols)
    height = 290 + 230 * (rows - 1)
    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=[p["title"] for p in panels],
        horizontal_spacing=0.07,
        vertical_spacing=70 / (height - 100) if rows > 1 else 0.0,
    )
    shown = set()
    for k, panel in enumerate(panels):
        r, c = k // cols + 1, k % cols + 1
        for s in panel["series"]:
            fig.add_trace(
                go.Scatter(
                    x=[wave_labels.index(w) for w, _, _ in s["points"]],
                    y=[mean for _, mean, _ in s["points"]],
                    mode="lines+markers",
                    name=s["name"],
                    legendgroup=s["name"],
                    showlegend=s["name"] not in shown,
                    line=dict(color=s["color"], width=1.2),
                    marker=dict(size=8, color=s["color"]),
                    customdata=[[w, n] for w, _, n in s["points"]],
                    hovertemplate=f"<b>{s['name']}</b> · %{{customdata[0]}}<br>mean %{{y:.2f}} · n %{{customdata[1]}}<extra></extra>",
                ),
                row=r,
                col=c,
            )
            shown.add(s["name"])
        fig.update_xaxes(
            row=r,
            col=c,
            tickvals=list(range(len(wave_labels))),
            ticktext=wave_labels,
            range=[-0.4, len(wave_labels) - 0.6],
            tickfont=dict(size=10),
            showgrid=False,
        )
    fig.update_annotations(font=dict(size=11, color=TITLE_INK))
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return base_layout(
        fig,
        height,
        margin=dict(l=60, r=20, t=60, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1 + 20 / (height - 100),
            x=1,
            xanchor="right",
            font=dict(size=10),
        ),
    )


def collection_pace(
    facets: list[dict], wave_labels: list[str], colors: dict[str, str]
) -> go.Figure:
    # Waves are aligned on their own start, so this round's pace sits on top of the last one's.
    fig = make_subplots(
        rows=1,
        cols=len(facets),
        subplot_titles=[f["title"] for f in facets],
        horizontal_spacing=0.12,
    )
    top = 0
    for c, facet in enumerate(facets, start=1):
        for wave in wave_labels:
            days = facet["days"].get(wave)
            if not days:
                continue
            weeks = np.sort(np.asarray(days, dtype=float)) / 7
            counts = np.arange(1, len(weeks) + 1)
            xs = np.concatenate([[0], np.repeat(weeks, 2)])
            ys = np.concatenate([[0, 0], np.repeat(counts, 2)])[: len(xs)]
            top = max(top, int(counts[-1]))
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    name=wave,
                    legendgroup=wave,
                    showlegend=c == 1,
                    line=dict(color=colors[wave], width=2),
                    hovertemplate=f"<b>{wave}</b> · week %{{x:.0f}}<br>%{{y}} {facet['unit']}<extra></extra>",
                ),
                row=1,
                col=c,
            )
            fig.add_trace(
                go.Scatter(
                    x=[weeks[-1]],
                    y=[counts[-1]],
                    mode="markers+text",
                    text=[str(counts[-1])],
                    textposition="middle right",
                    textfont=dict(color=colors[wave], size=11),
                    cliponaxis=False,
                    marker=dict(size=8, color=colors[wave], line=dict(color="white", width=1)),
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=1,
                col=c,
            )
    fig.update_xaxes(title_text="Weeks since the wave started", rangemode="tozero", gridcolor=GRID)
    fig.update_yaxes(range=[0, top * 1.1 or 1], gridcolor=GRID)
    fig.update_annotations(font=dict(size=12, color=TITLE_INK))
    return base_layout(
        fig,
        320,
        margin=dict(l=48, r=40, t=40, b=96),
        legend=dict(orientation="h", x=0, y=-0.3, yanchor="top"),
    )


def small_multiples(panels: list[dict], y_range: tuple[float, float], y_title: str) -> go.Figure:
    # Every panel draws its background lines faint grey and its own line in colour on top.
    cols = min(3, len(panels))
    rows = -(-len(panels) // cols)
    fig = make_subplots(
        rows=rows,
        cols=cols,
        subplot_titles=[p["title"] for p in panels],
        horizontal_spacing=0.06,
        vertical_spacing=0.18 / rows,
    )
    for k, panel in enumerate(panels):
        row, col = k // cols + 1, k % cols + 1
        positions = list(range(len(panel["x"])))
        xs, ys = [], []
        for line in panel["background"]:
            xs += [*positions, None]
            ys += [*line, None]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                line=dict(color="rgba(128,128,128,0.2)", width=1.2),
                showlegend=False,
                hoverinfo="skip",
            ),
            row=row,
            col=col,
        )
        highlight = panel["highlight"]
        fig.add_trace(
            go.Scatter(
                x=positions,
                y=highlight["values"],
                mode="lines+markers",
                name=highlight["name"],
                line=dict(color=highlight["color"], width=2),
                marker=dict(size=6, color=highlight["color"]),
                customdata=panel.get("hover", panel["x"]),
                hovertemplate=f"<b>{highlight['name']}</b><br>%{{customdata}}<br>%{{y:.2f}}<extra></extra>",
                showlegend=False,
            ),
            row=row,
            col=col,
        )
        fig.update_xaxes(
            tickvals=positions,
            ticktext=panel["x"],
            tickfont=dict(size=9),
            showgrid=False,
            range=[-0.3, len(positions) - 0.7],
            row=row,
            col=col,
        )
        fig.update_yaxes(
            range=list(y_range),
            gridcolor=GRID,
            zeroline=False,
            tickfont=dict(size=9),
            title_text=y_title if col == 1 else None,
            title_font=dict(size=10),
            row=row,
            col=col,
        )
    fig.update_annotations(font=dict(size=12, color=TITLE_INK))
    return base_layout(fig, 60 + 250 * rows, margin=dict(l=60, r=20, t=50, b=50))


def trajectories(
    people: list[tuple[str, list[float], list[float]]],
    means: list[tuple[float, float, int]],
    line: list[tuple[float, float]],
    ticks: list[tuple[float, str]] | None,
    x_title: str,
    y_title: str,
    color: str,
) -> go.Figure:
    # All people in one trace, split by gaps, so hundreds of lines stay quick to draw.
    xs, ys, ids = [], [], []
    for person, times, values in people:
        xs += [*times, None]
        ys += [*values, None]
        ids += [person] * len(times) + [None]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            customdata=ids,
            mode="lines+markers",
            name="Each person",
            line=dict(color=rgba(MUTED_INK, 0.35), width=0.8),
            marker=dict(size=3, color=rgba(MUTED_INK, 0.5)),
            hovertemplate="%{customdata}: %{y:.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[t for t, _ in line],
            y=[v for _, v in line],
            mode="lines",
            name="Fixed effects",
            line=dict(color=color, width=3),
            hovertemplate="predicted %{y:.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[t for t, _, _ in means],
            y=[m for _, m, _ in means],
            customdata=[n for _, _, n in means],
            mode="markers",
            name="Observed mean",
            marker=dict(size=9, color="white", line=dict(color=color, width=2)),
            hovertemplate="mean %{y:.2f} · n %{customdata}<extra></extra>",
        )
    )
    fig.update_xaxes(title_text=x_title, showgrid=False, zeroline=False)
    if ticks:
        fig.update_xaxes(
            tickvals=[t for t, _ in ticks],
            ticktext=[text for _, text in ticks],
            range=[ticks[0][0] - TRAJECTORY_PAD, ticks[-1][0] + TRAJECTORY_PAD],
        )
    fig.update_yaxes(title_text=y_title, gridcolor=GRID, zeroline=False)
    return base_layout(
        fig,
        380,
        margin=dict(l=64, r=16, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=1, xanchor="right"),
    )
