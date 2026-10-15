import re

from labcatalog.charts import style
from labcatalog.gui import preferences


def test_use_palette_recolors_waves_groups_and_pairs(monkeypatch):
    monkeypatch.setattr(style, "palette", style.palette)
    default = [style.wave_color(0), style.group_color(0), style.pair_color(0)]
    style.use_palette("okabe_ito")
    chosen = style.PALETTES["okabe_ito"]
    assert [style.wave_color(0), style.group_color(0), style.pair_color(1)] == [
        chosen.waves[0],
        chosen.groups[0],
        chosen.pair[1],
    ]
    assert style.wave_color(len(chosen.waves)) == chosen.waves[0]
    style.use_palette(style.DEFAULT_PALETTE)
    assert [style.wave_color(0), style.group_color(0), style.pair_color(0)] == default


def test_every_palette_is_complete():
    hex_color = re.compile(r"^#[0-9a-fA-F]{6}$")
    assert style.DEFAULT_PALETTE in style.PALETTES
    for palette in style.PALETTES.values():
        colors = [*palette.waves, *palette.groups, *palette.pair]
        assert len(palette.waves) >= 3 and len(palette.groups) >= 3 and len(palette.pair) == 2
        assert all(hex_color.match(c) for c in colors)


def test_preferences_keep_other_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(preferences, "folder", lambda: tmp_path / "labcatalog")
    assert preferences.load() == {}
    preferences.save({"palette": "lancet", "other": 1})
    preferences.save({"palette": "nature"})
    assert preferences.load() == {"palette": "nature", "other": 1}
