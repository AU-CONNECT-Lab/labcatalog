from nicegui import ui

from labcatalog import defaults
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui.common import computed
from labcatalog.pipeline import CatalogResult
from labcatalog.reports.database import write_database


def database_button(result: CatalogResult) -> None:
    async def build() -> None:
        button.props("loading")
        try:
            # From the data as loaded, so it matches what the window shows.
            await computed(write_database, result, result.project.root / defaults.DATABASE_FILE)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        finally:
            button.props(remove="loading")
        ui.notify(f"Wrote {defaults.DATABASE_FILE}")

    button = (
        ui.button("Build database", icon="storage", on_click=build)
        .props("flat no-caps")
        .tooltip(f"Writes every dataset, its variables and statistics to {defaults.DATABASE_FILE}")
    )
