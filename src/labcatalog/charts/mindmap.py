from html import escape

from labcatalog.charts.style import FONT, INK, LABEL_INK, MUTED_INK, group_color
from labcatalog.data.resolve import as_text_dict
from labcatalog.schema import Instrument, Item, Score

ROW_HEIGHT = 24
MIN_HEIGHT = 160
SHORT_TEXT = 40
UNSCORED = "Not in a score"


def instrument_tree(instrument: Instrument) -> dict:
    # Instrument, then its scores, then their items; a score made of all the others is one leaf.
    items = {item.id: item for item in instrument.items}
    summaries = summary_scores(instrument.scores)
    branches = []
    for score in instrument.scores:
        if score.id in summaries:
            branches.append(
                node(f"{score.label} ({score.method} of {len(score.items)})", score_tip(score))
            )
        else:
            children = [item_node(items[i]) for i in score.items if i in items]
            branches.append(node(f"{score.label} ({score.method})", score_tip(score), children))
    scored = {i for score in instrument.scores for i in score.items}
    loose = [item_node(item) for item in instrument.items if item.id not in scored]
    if loose and instrument.scores:
        branches.append(node(UNSCORED, f"{len(loose)} items in no score", loose))
    else:
        branches += loose
    if instrument.response_sets:
        sets = [
            node(s.id, "", [node(f"{o.value} = {o.label}", "") for o in s.options])
            for s in instrument.response_sets
        ]
        branches.append({**node("Answer options", "Click to show them", sets), "collapsed": True})
    for n, branch in enumerate(branches):
        paint(branch, group_color(n))
    root = node(
        instrument.abbreviation or instrument.id,
        f"<b>{escape(instrument.name)}</b>"
        + (f"<br>{escape(instrument.construct_name)}" if instrument.construct_name else ""),
        branches,
    )
    root["label"] = {"fontWeight": "bold", "fontSize": 13, "color": INK}
    root["itemStyle"] = {"color": INK, "borderColor": INK}
    return {
        "textStyle": {"fontFamily": FONT, "color": LABEL_INK},
        "tooltip": {"trigger": "item", "confine": True, "textStyle": {"fontSize": 11}},
        "series": [
            {
                "type": "tree",
                "data": [root],
                "orient": "LR",
                "top": 12,
                "bottom": 12,
                "left": 110,
                "right": 300,
                "symbolSize": 8,
                "initialTreeDepth": -1,
                "expandAndCollapse": True,
                "animationDuration": 300,
                # The panel's colour behind a label hides the lines that run under it.
                "label": {
                    "position": "left",
                    "verticalAlign": "middle",
                    "fontSize": 12,
                    "backgroundColor": "#ffffff",
                    "padding": [1, 3],
                },
                "leaves": {"label": {"position": "right", "align": "left"}},
                "lineStyle": {"color": MUTED_INK, "width": 1, "curveness": 0.5},
                "emphasis": {"focus": "descendant"},
            }
        ],
    }


def tree_height(option: dict) -> int:
    return max(MIN_HEIGHT, ROW_HEIGHT * shown_leaves(option["series"][0]["data"][0]))


def shown_leaves(tree: dict) -> int:
    children = tree.get("children") or []
    if not children or tree.get("collapsed"):
        return 1
    return sum(shown_leaves(child) for child in children)


def summary_scores(scores: list[Score]) -> set[str]:
    # A total holds every item of the other scores; drawing its items again would repeat them.
    found = set()
    for score in scores:
        others = {i for other in scores if other is not score for i in other.items}
        if others and others <= set(score.items):
            found.add(score.id)
    if len(found) == len(scores) and scores:
        found.discard(scores[0].id)
    return found


def node(name: str, tip: str, children: list[dict] | None = None) -> dict:
    found = {"name": name, "tooltip": {"formatter": tip or escape(name)}}
    if children:
        found["children"] = children
    return found


def item_node(item: Item) -> dict:
    text = " / ".join(as_text_dict(item.text).values())
    short = item.label or (text if len(text) <= SHORT_TEXT else text[: SHORT_TEXT - 1] + "…")
    reverse = " (R)" if item.reverse else ""
    details = [item.type]
    if item.response_set:
        details.append(f"answered on {item.response_set}")
    if item.min is not None or item.max is not None:
        details.append(f"from {item.min} to {item.max}")
    if item.reverse:
        details.append("reverse-scored")
    tip = f"<b>{escape(item.id)}</b><br>{escape(text)}<br>{escape(', '.join(details))}"
    return node(f"{item.id}  {short}{reverse}", tip)


def score_tip(score: Score) -> str:
    rule = {"complete": "every item answered", "prorate": "prorated", "zero": "missing as 0"}
    return (
        f"<b>{escape(score.label)}</b> ({escape(score.id)})<br>{score.method} of "
        f"{len(score.items)} items, {rule[score.missing_rule]}<br>{escape(', '.join(score.items))}"
    )


def paint(tree: dict, color: str) -> None:
    tree["itemStyle"] = {"color": color, "borderColor": color}
    for child in tree.get("children") or []:
        paint(child, color)
