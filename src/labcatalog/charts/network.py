import numpy as np

from labcatalog.charts.style import (
    CORRELATION_SCALE,
    FONT,
    INK,
    LABEL_INK,
    scale_color,
)

NODE_MIN = 7
NODE_SPAN = 11
NETWORK_HEIGHT = 640
UNSET = "Not set"
UNSET_COLOR = "#9aa5b1"
# Links shown at |r| from the chart's threshold up use the stronger part of the colour scale.
LINK_FLOOR = 0.35
# The force settings suit about this many nodes; more nodes get shorter links and a stronger pull
# to the centre, so groups with no link between them stay in view.
SPACED_NODES = 12
# Beyond this, names show on hover only, as they would overlap.
LABELLED_NODES = 40


def score_network(
    nodes: list[dict], links: list[dict], categories: list[tuple[str, str]], pinned: bool = False
) -> dict:
    # ECharts force layout: strongly related scores pull together, colour shows the chosen grouping.
    strength = np.zeros(len(nodes))
    for link in links:
        strength[[link["source"], link["target"]]] += abs(link["r"])
    peak = strength.max() or 1.0
    top = max((abs(link["r"]) for link in links), default=1.0)
    data = [
        {
            "id": node["key"],
            "name": node["label"],
            "category": node["category"],
            "symbolSize": round(NODE_MIN + NODE_SPAN * strength[i] / peak, 2),
            "tooltip": {"formatter": node["tip"]},
            # Pinned while only the colours change, so the nodes keep their places.
            "fixed": pinned,
        }
        for i, node in enumerate(nodes)
    ]
    edges = [
        {
            "source": nodes[link["source"]]["key"],
            "target": nodes[link["target"]]["key"],
            "value": abs(link["r"]),
            "lineStyle": {
                "color": scale_color(
                    np.sign(link["r"]) * (LINK_FLOOR + (1 - LINK_FLOOR) * abs(link["r"])),
                    CORRELATION_SCALE,
                    -1,
                    1,
                ),
                "width": round(2 * (0.25 + 0.75 * (abs(link["r"]) / top) ** 1.5), 2),
            },
            "tooltip": {"formatter": link["tip"]},
        }
        for link in links
    ]
    spread = min(1.0, SPACED_NODES / len(nodes)) ** 0.5
    return {
        "backgroundColor": "white",
        "textStyle": {"fontFamily": FONT, "color": INK},
        "tooltip": {"confine": True, "textStyle": {"fontSize": 11}},
        "legend": {
            "data": [name for name, _ in categories],
            "type": "scroll",
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
                "top": 16,
                "bottom": 40,
                "data": data,
                "links": edges,
                "categories": [{"name": n, "itemStyle": {"color": c}} for n, c in categories],
                "itemStyle": {"opacity": 0.9, "borderColor": "#fff", "borderWidth": 0.5},
                "lineStyle": {"opacity": 0.85},
                "label": {
                    "show": len(nodes) <= LABELLED_NODES,
                    "position": "right",
                    "fontSize": 10,
                    "color": LABEL_INK,
                    "backgroundColor": "rgba(255,255,255,0.75)",
                },
                "emphasis": {
                    "focus": "adjacency",
                    "label": {"show": True},
                    "lineStyle": {"width": 3},
                },
                # Low friction lets the layout drift and settle slowly; ids keep places across updates.
                "force": {
                    "initLayout": "none",
                    "friction": 0.2,
                    "repulsion": round(900 * spread**2),
                    "gravity": round(0.03 / spread**2, 3),
                    "edgeLength": [round(90 * spread), round(280 * spread)],
                },
            }
        ],
    }
