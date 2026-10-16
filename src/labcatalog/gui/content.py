from collections.abc import Awaitable, Callable

from nicegui import run, ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import preferences


def get_button(
    label: str,
    function: Callable[..., None],
    args: list,
    on_done: Callable[[], Awaitable[None]],
) -> None:
    async def go() -> None:
        datalad = preferences.load().get(preferences.DATALAD)
        if not datalad:
            ui.notify("Set the path to datalad on the Settings page first", type="warning")
            return
        button.props("loading")
        try:
            await run.io_bound(function, *args, datalad)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        finally:
            button.props(remove="loading")
        await on_done()

    button = ui.button(label, icon="download", on_click=go).props("flat dense no-caps")
