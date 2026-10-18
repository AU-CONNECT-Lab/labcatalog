import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from labcatalog.charts import style
from labcatalog.config import ProjectConfig
from labcatalog.gui import common, look
from labcatalog.gui.look import Look, scoped, within


def test_a_thread_draws_with_the_window_that_handed_it_the_work():
    mine = Look(palette="lancet", decimals=4)
    mine.use_project(ProjectConfig(project={"name": "x"}, stats={"decimals": 3}))
    with ThreadPoolExecutor(1) as pool:
        shown = pool.submit(scoped, mine, common.fmt, 0.5).result()
        # The thread keeps nothing once the work is done.
        after = pool.submit(common.fmt, 0.5).result()
    assert (shown, after) == ("0.500", "0.50")


def test_a_window_background_task_keeps_its_look_and_leaves_others_alone():
    first, second = Look(decimals=1), Look(decimals=4)

    async def place() -> str:
        await asyncio.sleep(0)
        return common.fmt(0.5)

    async def both() -> list[str]:
        return await asyncio.gather(
            asyncio.create_task(within(first, place())),
            asyncio.create_task(within(second, place())),
            asyncio.create_task(place()),
        )

    assert asyncio.run(both()) == ["0.5", "0.5000", "0.50"]


def test_the_palette_follows_the_look(monkeypatch):
    monkeypatch.setattr(style, "palette_of", style.default_palette)
    look.install()
    try:
        assert style.wave_color(0) == style.PALETTES[style.DEFAULT_PALETTE].waves[0]
        mine = Look(palette="okabe_ito")
        assert scoped(mine, style.wave_color, 0) == style.PALETTES["okabe_ito"].waves[0]
    finally:
        style.palette_of = style.default_palette


def test_redraw_touches_only_the_copies_drawn_for_that_window():
    drawn = []

    def target(owner):
        container = SimpleNamespace(clear=lambda: drawn.append(("clear", owner)))
        return SimpleNamespace(args=("result", owner), container=container, run=lambda f: f(owner))

    mine, theirs = object(), object()
    function = SimpleNamespace(
        targets=[target(mine), target(theirs)],
        prune=lambda: None,
        func=lambda owner: drawn.append(("draw", owner)),
    )
    common.redraw(function, mine)
    assert drawn == [("clear", mine), ("draw", mine)]
