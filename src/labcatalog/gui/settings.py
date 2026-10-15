from collections.abc import Awaitable, Callable

from nicegui import run, ui

from labcatalog.charts import style
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences
from labcatalog.gui.common import note, section
from labcatalog.rbridge import ALL_PACKAGES, install_command, r_status

RSCRIPT_EXAMPLE = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"


def render(on_palette: Callable[[str], None], on_rscript: Callable[[], Awaitable[None]]) -> None:
    section("R")
    note(
        "Factor models (CFA) and ω run in R with lavaan and semTools, and the Analysis page "
        "uses R first, with psych and effectsize; without R it uses Python. Install R and "
        f"the packages yourself ({install_command(ALL_PACKAGES)}), then give the path to "
        f"Rscript, which is in R's bin folder, for example {RSCRIPT_EXAMPLE}."
    )
    path = (
        ui.input("Rscript", value=preferences.load().get(preferences.RSCRIPT, ""))
        .props("outlined dense clearable")
        .classes("w-full max-w-2xl mt-2")
    )
    status = ui.label().classes("lc-note")

    async def save() -> None:
        # Windows' "Copy as path" wraps the path in quotes.
        value = (path.value or "").strip().strip('"')
        path.value = value
        preferences.save({preferences.RSCRIPT: value})
        if not value:
            status.set_text("No Rscript set: no factor models, and the Analysis page uses Python.")
            await on_rscript()
            return
        status.set_text("Checking R")
        try:
            found = await run.io_bound(r_status, value)
        except LabCatalogError as err:
            status.set_text(str(err))
            return
        if found.missing:
            status.set_text(
                f"{found.version}, but it is missing {', '.join(found.missing)}; "
                f"install them in R with: {install_command(found.missing)}"
            )
        else:
            status.set_text(f"{found.version}, with every package labcatalog uses.")
        await on_rscript()

    ui.button("Save and check", on_click=save).classes("mt-2")

    section("Charts")
    ui.select(
        {name: p.label for name, p in style.PALETTES.items()},
        value=style.palette,
        label="Chart colors",
        on_change=lambda e: on_palette(e.value),
    ).props("outlined dense").classes("w-56 mt-2")
