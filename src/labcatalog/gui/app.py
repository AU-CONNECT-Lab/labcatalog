from pathlib import Path

import webview
from nicegui import app, background_tasks, run, ui

from labcatalog.browse import BrowseIndex, build_index
from labcatalog.charts import style
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import (
    analysis,
    codebook_import,
    datasets,
    instruments,
    overview,
    preferences,
    prepare,
    problems,
    settings,
    theme,
)
from labcatalog.gui.analysis import AnalysisView
from labcatalog.gui.codebook_import import ImportView
from labcatalog.gui.instruments import (
    CFA_DONE,
    CFA_FAILED,
    CFA_RUNNING,
    CFA_UNSET,
    BrowseView,
    CfaView,
)
from labcatalog.gui.prepare import PrepareView
from labcatalog.pipeline import CatalogResult, run_catalog, run_cfa
from labcatalog.version import __version__

WINDOW_SIZE = (1280, 820)
PAGES = (
    ("overview", "Overview", "dashboard"),
    ("instruments", "Instruments", "list_alt"),
    ("datasets", "Datasets", "table_chart"),
    ("analysis", "Analysis", "query_stats"),
    ("prepare", "Prepare", "play_circle"),
    ("import", "Import", "upload_file"),
    ("problems", "Problems", "report_problem"),
    ("settings", "Settings", "settings"),
)


def launch(project: Path | None = None) -> None:
    theme.install()
    saved = preferences.load().get(preferences.PALETTE)
    # A palette saved by another version may no longer exist.
    style.use_palette(saved if saved in style.PALETTES else style.DEFAULT_PALETTE)
    # Saving a table or figure goes through the window's own save dialog.
    app.native.settings["ALLOW_DOWNLOADS"] = True
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
        self.index: BrowseIndex | None = None
        self.view = BrowseView()
        self.analysis = AnalysisView()
        self.importing = ImportView()
        self.preparing = PrepareView()
        self.cfa = CfaView()
        self.dataset: str | None = None
        self.error: str | None = None

    def build(self) -> None:
        with ui.header().classes("lc-header items-center gap-4 px-5 py-3"):
            self.title = ui.label("No project open").classes("lc-project")
            with self.title:
                self.path_tip = ui.tooltip("")
            self.as_of = ui.label().classes("lc-as-of")
            ui.space()
            self.spinner = ui.spinner(size="sm")
            self.spinner.visible = False
            self.refresh_button = (
                ui.button("Refresh", icon="refresh", on_click=lambda: self.load(self.root))
                .props("flat")
                .classes("lc-quiet-btn")
            )
            self.refresh_button.disable()
            self.open_button = ui.button(
                "Open project", icon="folder_open", on_click=self.choose_folder
            )

        with ui.left_drawer(value=True, fixed=True).props("width=220").classes("p-0"):
            ui.label("labcatalog").classes("lc-wordmark")
            with (
                ui.tabs(value="overview")
                .props("vertical inline-label no-caps")
                .classes("lc-nav w-full") as tabs
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
            with ui.tab_panel("overview").classes("lc-board"):
                self.overview_panel()
            with ui.tab_panel("instruments").classes("lc-paper"):
                self.instruments_panel()
            with ui.tab_panel("datasets").classes("lc-paper"):
                self.datasets_panel()
            with ui.tab_panel("analysis").classes("lc-paper"):
                self.analysis_panel()
            with ui.tab_panel("prepare").classes("lc-paper"):
                self.prepare_panel()
            with ui.tab_panel("import").classes("lc-paper"):
                self.import_panel()
            with ui.tab_panel("problems").classes("lc-paper"):
                self.problems_panel()
            with ui.tab_panel("settings").classes("lc-paper"):
                settings.render(self.set_palette, self.start_cfa)

    async def choose_folder(self) -> None:
        selection = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
        if selection:
            await self.load(Path(selection[0]))

    async def load(self, root: Path) -> None:
        self.set_busy(True)
        try:
            result = await run.io_bound(run_catalog, root)
        except LabCatalogError as err:
            # The project stays open so the Prepare page can make the missing data.
            ui.notify(str(err), type="negative", multi_line=True)
            result, self.error = None, str(err)
        else:
            self.error = None
        finally:
            # Refreshing keeps the filters; opening another project starts over.
            if root != self.root:
                self.view = BrowseView()
                self.analysis = AnalysisView()
                self.importing = ImportView()
                self.preparing = PrepareView()
                self.root = root
            self.set_busy(False)
        self.result = result
        self.show_result()
        # R is slow, so the factor models fill in after the rest of the catalog shows.
        background_tasks.create(self.start_cfa())

    async def start_cfa(self) -> None:
        result, cfa = self.result, self.cfa
        rscript = preferences.load().get(preferences.RSCRIPT)
        cfa.fits, cfa.message = [], ""
        if result is None or result.project is None or not rscript:
            cfa.status = CFA_UNSET
            instruments.cfa_changed()
            return
        cfa.status = CFA_RUNNING
        instruments.cfa_changed()
        try:
            fits = await run.io_bound(run_cfa, result, rscript)
        except LabCatalogError as err:
            fits, message, status = [], str(err), CFA_FAILED
        else:
            message, status = "", CFA_DONE
        # A newer Refresh has started its own run.
        if self.result is not result:
            return
        cfa.fits, cfa.message, cfa.status = fits, message, status
        instruments.cfa_changed()

    def set_palette(self, name: str) -> None:
        style.use_palette(name)
        preferences.save({preferences.PALETTE: name})
        if self.result is not None:
            self.show_result()

    def set_busy(self, busy: bool) -> None:
        self.spinner.visible = busy
        self.open_button.set_enabled(not busy)
        self.refresh_button.set_enabled(not busy and self.root is not None)

    def show_result(self) -> None:
        result = self.result
        project = result.project if result else None
        self.title.set_text(project.config.project.name if project else self.root.name)
        self.path_tip.set_text(str(self.root))
        self.as_of.set_text(as_of_text(result) if result else "")
        self.index = build_index(project) if project else None
        issues = result.report.issues if result else []
        failed = result is not None and result.report.has_errors()
        self.badge.set_text(str(len(issues)))
        self.badge.props(f"color={'negative' if failed else 'primary'}")
        self.badge.visible = bool(issues)
        if result is not None and project is None:
            self.tabs.set_value("problems")
        for panel in (
            self.overview_panel,
            self.instruments_panel,
            self.datasets_panel,
            self.analysis_panel,
            self.prepare_panel,
            self.import_panel,
            self.problems_panel,
        ):
            panel.refresh()

    def open_instrument(self, instrument_id: str | None) -> None:
        self.view.instrument = instrument_id
        self.instruments_panel.refresh()
        self.tabs.set_value("instruments")

    def show_dataset(self, dataset: str | None) -> None:
        self.dataset = dataset
        self.datasets_panel.refresh()

    @ui.refreshable_method
    def overview_panel(self) -> None:
        if self.has_catalog():
            overview.render(
                self.result,
                lambda: self.open_instrument(None),
                lambda: self.tabs.set_value("problems"),
            )

    @ui.refreshable_method
    def instruments_panel(self) -> None:
        if self.has_catalog():
            instruments.render(self.result, self.index, self.view, self.open_instrument, self.cfa)

    @ui.refreshable_method
    def datasets_panel(self) -> None:
        if self.has_catalog():
            datasets.render(self.result, self.dataset, self.show_dataset, self.open_instrument)

    @ui.refreshable_method
    def analysis_panel(self) -> None:
        if self.has_catalog():
            analysis.render(self.result, self.analysis)

    @ui.refreshable_method
    def prepare_panel(self) -> None:
        if self.root is None:
            ui.label("Open a project folder to run its prepare steps.").classes("lc-note")
        else:
            prepare.render(self.root, self.preparing, lambda: self.load(self.root))

    @ui.refreshable_method
    def import_panel(self) -> None:
        if self.has_catalog():
            codebook_import.render(self.result, self.importing)

    @ui.refreshable_method
    def problems_panel(self) -> None:
        if self.result is None:
            ui.label(self.error or "Open a project folder to check it.").classes("lc-note")
        else:
            problems.render(self.result.report.issues, self.root)

    def has_catalog(self) -> bool:
        if self.result is None:
            ui.label(self.error or "Open a project folder to see its catalog.").classes("lc-note")
        elif self.result.project is None:
            ui.label("The project files have errors. Fix them, then press Refresh.").classes(
                "lc-note"
            )
        return self.result is not None and self.result.project is not None


def as_of_text(result: CatalogResult) -> str:
    if result.summary is None:
        return ""
    dates = sorted({d.snapshot_date for d in result.summary.datasets if d.snapshot_date})
    if not dates:
        return ""
    return f"Data as of {dates[0]}" + (f" to {dates[-1]}" if len(dates) > 1 else "")
