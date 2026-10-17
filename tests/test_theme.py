from labcatalog.gui import theme
from labcatalog.gui.theme import MIN_FONT, for_page


def test_for_page_raises_small_fonts_and_leaves_marks_alone():
    figure = {
        "data": [{"marker": {"size": 6}, "textfont": {"size": 9, "color": "red"}}],
        "layout": {
            "font": {"family": "Segoe UI"},
            "xaxis": {"tickfont": {"size": 9}, "title": {"font": {"size": 14}}},
            "paper_bgcolor": "white",
        },
    }
    shown = for_page(figure)
    assert shown["data"][0]["marker"] == {"size": 6}
    assert shown["data"][0]["textfont"] == {"size": MIN_FONT, "color": "red"}
    assert shown["layout"]["xaxis"]["tickfont"]["size"] == MIN_FONT
    assert shown["layout"]["xaxis"]["title"]["font"]["size"] == 14
    assert shown["layout"]["font"] == {"family": "Segoe UI"}
    assert shown["layout"]["paper_bgcolor"] == "rgba(0,0,0,0)"


def test_dark_figures_flip_greys_and_keep_hues(monkeypatch):
    monkeypatch.setattr(theme, "dark", True)
    figure = {
        "data": [{"marker": {"color": ["#3498db", "#ffffff"], "line": {"color": "white"}}}],
        "layout": {
            "font": {"color": "#1c2530"},
            "plot_bgcolor": "white",
            "xaxis": {"gridcolor": "#f2f2f2", "title": {"text": "black"}},
        },
    }
    shown = for_page(figure)
    assert shown["data"][0]["marker"]["color"][0] == "#3498db"
    assert shown["data"][0]["marker"]["line"]["color"] == "rgba(31,31,34,1)"
    assert shown["layout"]["plot_bgcolor"] == "rgba(0,0,0,0)"
    ink = theme.parse_color(shown["layout"]["font"]["color"])[0]
    grid = theme.parse_color(shown["layout"]["xaxis"]["gridcolor"])[0]
    assert min(ink) > 180 and max(grid) < 60
    assert shown["layout"]["xaxis"]["title"]["text"] == "black"
    assert theme.echart_for_page({"textStyle": {"color": "#333"}})["textStyle"]["color"] != "#333"


def test_light_figures_keep_their_colors():
    assert theme.echart_for_page({"textStyle": {"color": "#333"}})["textStyle"]["color"] == "#333"
    assert theme.parse_color("rgba(10, 20, 30, 0.5)") == ((10, 20, 30), 0.5)
    assert theme.parse_color("#abc") == ((170, 187, 204), 1.0)
    assert theme.parse_color("not a color") is None
