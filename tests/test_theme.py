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
