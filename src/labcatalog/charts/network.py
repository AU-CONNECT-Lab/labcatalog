import numpy as np

from labcatalog.charts.style import (
    CORRELATION_SCALE,
    FONT,
    INK,
    LABEL_INK,
    MUTED_INK,
    TITLE_INK,
    scale_color,
)

NODE_MIN = 7
NODE_SPAN = 11
NETWORK_HEIGHT = 640
UNSET = "Not set"
UNSET_COLOR = "#9aa5b1"


def score_network(
    nodes: list[dict], links: list[dict], categories: list[tuple[str, str]], title: str, note: str
) -> dict:
    # ECharts force layout: strongly related scores pull together, colour shows the chosen grouping.
    strength = np.zeros(len(nodes))
    for link in links:
        strength[[link["source"], link["target"]]] += abs(link["r"])
    peak = strength.max() or 1.0
    top = max((abs(link["r"]) for link in links), default=1.0)
    data = [
        {
            "id": str(i),
            "name": node["label"],
            "category": node["category"],
            "symbolSize": round(NODE_MIN + NODE_SPAN * strength[i] / peak, 2),
            "tooltip": {"formatter": node["tip"]},
        }
        for i, node in enumerate(nodes)
    ]
    edges = [
        {
            "source": str(link["source"]),
            "target": str(link["target"]),
            "value": abs(link["r"]),
            "lineStyle": {
                "color": scale_color(link["r"], CORRELATION_SCALE, -1, 1),
                "width": round(2 * (0.25 + 0.75 * (abs(link["r"]) / top) ** 1.5), 2),
            },
            "tooltip": {"formatter": link["tip"]},
        }
        for link in links
    ]
    return {
        "textStyle": {"fontFamily": FONT, "color": INK},
        "title": {
            "text": title,
            "subtext": note,
            "left": 0,
            "top": 0,
            "textStyle": {"fontSize": 13, "fontWeight": "normal", "color": TITLE_INK},
            "subtextStyle": {"fontSize": 10, "color": MUTED_INK},
        },
        "tooltip": {"confine": True, "textStyle": {"fontSize": 11}},
        "legend": {
            "data": [name for name, _ in categories],
            "bottom": 0,
            "icon": "circle",
            "itemWidth": 10,
            "itemHeight": 10,
            "textStyle": {"fontSize": 10},
        },
        "series": [
            {
                "type": "graph",
                "layout": "force",
                "roam": True,
                "draggable": True,
                "top": 56,
                "bottom": 40,
                "data": data,
                "links": edges,
                "categories": [{"name": n, "itemStyle": {"color": c}} for n, c in categories],
                "itemStyle": {"opacity": 0.9, "borderColor": "#fff", "borderWidth": 0.5},
                "lineStyle": {"opacity": 0.6},
                "label": {"show": True, "position": "right", "fontSize": 10, "color": LABEL_INK},
                "labelLayout": {"hideOverlap": True},
                "emphasis": {"focus": "adjacency", "lineStyle": {"width": 3}},
                "force": {
                    "initLayout": "circular",
                    "repulsion": 160,
                    "gravity": 0.08,
                    "edgeLength": [40, 140],
                },
            }
        ],
    }
