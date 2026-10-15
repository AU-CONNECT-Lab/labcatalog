from pathlib import Path

import webview
from nicegui import app, run, ui

from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import charts, datasets, instruments, overview, problems
from labcatalog.pipeline import CatalogResult, run_catalog
from labcatalog.version import __version__

WINDOW_SIZE = (1280, 820)
PAGES = (
    ("overview", "Overview", "dashboard"),
    ("instruments", "Instruments", "list_alt"),
    ("datasets", "Datasets", "table_chart"),
    ("correlations", "Correlations", "hub"),
    ("problems", "Problems", "report_problem"),
)


def launch(project: Path | None = None) -> None:
    ui.run(
        root=lambda: main_page(project),
        title=f"labcatalog {__version__}",
        native=True,
        window_size=WINDOW_SIZE,
        reload=False,
        show_welcome_message=False,
    )


def main_page(project: Path | None) -> None:
    # A packaged app has no console, so unexpected errors must show up in the window.
    ui.on_exception(
        lambda err: ui.notify(
            f"Unexpected error: {err!r}", type="negative", multi_line=True, timeout=0
        )
    )
    window = Window()
    window.build()
    if project is not None:
        ui.timer(0, lambda: window.load(project.resolve()), once=True)


class Window:
    def __init__(self) -> None:
        self.root: Path | None = None
        self.result: CatalogResult | None = None
        self.instrument: str | None = None
        self.dataset: str | None = None

    def build(self) -> None:
        ui.query("body").classes("bg-grey-1")
        with ui.header().classes(
            "items-center gap-4 px-4 py-2 bg-white text-grey-9 border-b border-gray-200"
        ):
            self.title = ui.label("No project open").classes("text-lg font-medium")
            with self.title:
                self.path_tip = ui.tooltip("")
            self.as_of = ui.label().classes("text-grey-7")
            ui.space()
            self.spinner = ui.spinner(size="sm")
            self.spinner.visible = False
            self.open_button = ui.button(
                "Open project", icon="folder_open", on_click=self.choose_folder
            ).props("flat no-caps")
            self.refresh_button = ui.button(
                "Refresh", icon="refresh", on_click=lambda: self.load(self.root)
            ).props("flat no-caps")
            self.refresh_button.disable()

        with ui.left_drawer(value=True, fixed=True).props("width=190 bordered").classes("p-0"):
            with (
                ui.tabs(value="overview")
                .props("vertical inline-label no-caps")
                .classes("w-full") as tabs
            ):
                nav = {
                    name: ui.tab(name, label=label, icon=icon).props(
                        'content-class="w-full justify-start pl-2"'
                    )
                    for name, label, icon in PAGES
                }
                with nav["problems"]:
                    self.badge = ui.badge().classes("ml-2")
                    self.badge.visible = False
        self.tabs = tabs

        with ui.tab_panels(tabs, value="overview").classes("w-full bg-transparent"):
            with ui.tab_panel("overview"):
                self.overview_panel()
            with ui.tab_panel("instruments"):
                self.instruments_panel()
            with ui.tab_panel("datasets"):
                self.datasets_panel()
            with ui.tab_panel("correlations"):
                self.correlations_panel()
            with ui.tab_panel("problems"):
                self.problems_panel()

    async def choose_folder(self) -> None:
        selection = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
        if selection:
            await self.load(Path(selection[0]))

    async def load(self, root: Path) -> None:
        self.set_busy(True)
        try:
            result = await run.io_bound(run_catalog, root)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
        else:
            self.root, self.result = root, result
            self.show_result()
        finally:
            self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.spinner.visible = busy
        self.open_button.set_enabled(not busy)
        self.refresh_button.set_enabled(not busy and self.root is not None)

    def show_result(self) -> None:
        result = self.result
        self.title.set_text(
            result.project.config.project.name if result.project else self.root.name
        )
        self.path_tip.set_text(str(self.root))
        self.as_of.set_text(as_of_text(result))
        issues = result.report.issues
        self.badge.set_text(str(len(issues)))
        self.badge.props(f"color={'negative' if result.report.has_errors() else 'orange-8'}")
        self.badge.visible = bool(issues)
        if result.project is None:
            self.tabs.set_value("problems")
        for panel in (
            self.overview_panel,
            self.instruments_panel,
            self.datasets_panel,
            self.correlations_panel,
            self.problems_panel,
        ):
            panel.refresh()

    def show_instrument(self, instrument_id: str) -> None:
        self.instrument = instrument_id
        self.instruments_panel.refresh()
        self.tabs.set_value("instruments")

    def show_dataset(self, dataset: str) -> None:
        self.dataset = dataset
        self.datasets_panel.refresh()

    @ui.refreshable_method
    def overview_panel(self) -> None:
        if self.has_catalog():
            overview.render(
                self.result, self.show_instrument, lambda: self.tabs.set_value("problems")
            )

    @ui.refreshable_method
    def instruments_panel(self) -> None:
        if self.has_catalog():
            instruments.render(self.result, self.instrument, self.show_instrument)

    @ui.refreshable_method
    def datasets_panel(self) -> None:
        if self.has_catalog():
            datasets.render(self.result, self.dataset, self.show_dataset)

    @ui.refreshable_method
    def correlations_panel(self) -> None:
        if self.has_catalog():
            charts.correlations_page(self.result)

    @ui.refreshable_method
    def problems_panel(self) -> None:
        if self.result is None:
            ui.label("Open a project folder to check it.").classes("text-grey-7")
        else:
            problems.render(self.result.report.issues, self.root)

    def has_catalog(self) -> bool:
        if self.result is None:
            ui.label("Open a project folder to see its catalog.").classes("text-grey-7")
        elif self.result.project is None:
            ui.label("The project files have errors. Fix them, then press Refresh.").classes(
                "text-grey-7"
            )
        return self.result is not None and self.result.project is not None


def as_of_text(result: CatalogResult) -> str:
    if result.summary is None:
        return ""
    dates = sorted({d.snapshot_date for d in result.summary.datasets if d.snapshot_date})
    if not dates:
        return ""
    return f"Data as of {dates[0]}" + (f" to {dates[-1]}" if len(dates) > 1 else "")
