import numpy as np

from labcatalog.charts.style import CORRELATION_SCALE, scale_color

UNSET_COLOR = "#9aa5b1"
# Links shown at |r| from the chart's threshold up use the stronger part of the colour scale.
LINK_FLOOR = 0.35
# The catalog map: structure links are short, links between correlated scores long and loose.
MAP_HEIGHT = 720
MAP_FORCE = {"repel": 40, "gravity": 0.06, "length": [12, 60]}
CORRELATION_PULL = 0.2


def sign_color(r: float) -> str:
    return scale_color(
        np.sign(r) * (LINK_FLOOR + (1 - LINK_FLOOR) * abs(r)), CORRELATION_SCALE, -1, 1
    )


def catalog_map(nodes: list[dict], links: list[dict], groups: list[tuple[str, str]]) -> dict:
    # Instruments hold their scores and scores their items; a link with an r joins correlated scores.
    degree: dict[str, int] = {}
    for link in links:
        for end in (link["source"], link["target"]):
            degree[end] = degree.get(end, 0) + 1
    return {
        "nodes": [
            {**node, "size": round(1.2 + 1.1 * degree.get(node["id"], 0) ** 0.5, 2)}
            for node in nodes
        ],
        "links": [
            {
                "source": link["source"],
                "target": link["target"],
                "value": 1.0 if link["r"] is None else CORRELATION_PULL * abs(link["r"]),
                "color": UNSET_COLOR if link["r"] is None else sign_color(link["r"]),
                "width": 1.0 if link["r"] is None else round(0.6 + 1.4 * abs(link["r"]), 2),
                "tip": link["tip"],
            }
            for link in links
        ],
        "groups": [{"name": name, "color": color} for name, color in groups],
        "force": MAP_FORCE,
    }
