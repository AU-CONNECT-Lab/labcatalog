from collections.abc import Callable
from pathlib import Path

import webview
from nicegui import app, background_tasks, ui

from labcatalog.charts import style
from labcatalog.datalad.annex import dataset_root
from labcatalog.datalad.bridge import use_folder
from labcatalog.datalad.freeze import list_freezes
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import (
    analysis,
    codebook_import,
    common,
    datasets,
    edit,
    example,
    fix,
    instruments,
    methods,
    new_dataset,
    overview,
    preferences,
    prepare,
    problems,
    settings,
    studies,
    theme,
)
from labcatalog.gui.analysis import AnalysisView
from labcatalog.gui.codebook_import import ImportView
from labcatalog.gui.datalad import frozen_text, get_button
from labcatalog.gui.edit import EditView
from labcatalog.gui.instruments import (
    CFA_DONE,
    CFA_FAILED,
    CFA_RUNNING,
    CFA_UNSET,
    BrowseView,
    CfaView,
)
from labcatalog.gui.methods import MethodsView
from labcatalog.gui.prepare import PrepareView
from labcatalog.gui.studies import StudiesView
from labcatalog.issues import Issue
from labcatalog.metadata.browse import BrowseIndex, build_index
from labcatalog.pipeline import (
    CatalogResult,
    run_catalog,
    run_cfa,
    run_get_missing,
    run_invariance,
    run_open_freeze,
)
from labcatalog.version import __version__

WINDOW_SIZE = (1280, 820)
# Groups of pages, drawn with a line between them; Settings is the gear in the header.
PAGES = (
    (
        ("overview", "Overview"),
        ("instruments", "Instruments"),
        ("studies", "Studies"),
        ("datasets", "Datasets"),
    ),
    (("analysis", "Analysis"), ("methods", "Methods")),
    (("prepare", "Prepare"), ("import", "Import"), ("edit", "Edit")),
    (("problems", "Problems"),),
)
SETTINGS = "settings"


def launch(project: Path | None = None) -> None:
    theme.install()
    saved = preferences.load().get(preferences.PALETTE)
    # A palette saved by another version may no longer exist.
    style.use_palette(saved if saved in style.PALETTES else style.DEFAULT_PALETTE)
    common.set_decimals(preferences.load().get(preferences.DECIMALS, preferences.DEFAULT_DECIMALS))
    if datalad := preferences.load().get(preferences.DATALAD):
        use_folder(datalad)
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
    start = project.resolve() if project is not None else example.start_folder()
    ui.timer(0, lambda: window.open_project(start), once=True)


class Window:
    def __init__(self) -> None:
        self.root: Path | None = None
        self.result: CatalogResult | None = None
        self.index: BrowseIndex | None = None
        self.view = BrowseView()
        self.studying = StudiesView()
        self.analysis = AnalysisView()
        self.methods = MethodsView()
        self.importing = ImportView()
        self.editing = EditView()
        self.preparing = PrepareView()
        self.cfa = CfaView(
            open_settings=lambda: self.tabs.set_value("settings"), reload=self.reload
        )
        self.dataset: str | None = None
        self.error: str | None = None
        # The project a frozen copy was opened from, while the copy is shown.
        self.home: Path | None = None

    def build(self) -> None:
        appearance = preferences.load().get(preferences.APPEARANCE, theme.DEFAULT_APPEARANCE)
        # A value saved by another version may no longer exist.
        appearance = appearance if appearance in theme.APPEARANCES else theme.DEFAULT_APPEARANCE
        self.dark_mode = ui.dark_mode(theme.mode_value(appearance))
        theme.set_dark(appearance == theme.DARK)
        if appearance == theme.SYSTEM:
            ui.timer(0, self.follow_system, once=True)
        with ui.header().classes("lc-header block px-6 pt-3 pb-0"):
            with ui.row().classes("w-full items-center gap-4"):
                self.title = ui.label("No project open").classes("lc-project")
                with self.title:
                    self.path_tip = ui.tooltip("")
                self.as_of = ui.label().classes("lc-as-of")
                with ui.row().classes("items-center gap-2") as self.frozen_bar:
                    self.frozen_label = ui.label().classes("lc-as-of")
                    ui.button("Back to the project", on_click=self.leave_freeze).props(
                        "flat no-caps"
                    ).classes("lc-quiet-btn")
                self.frozen_bar.visible = False
                ui.space()
                self.spinner = ui.spinner(size="sm")
                self.spinner.visible = False
                self.refresh_button = (
                    ui.button("Refresh", icon="refresh", on_click=lambda: self.load(self.root))
                    .props("flat")
                    .classes("lc-quiet-btn")
                )
                self.refresh_button.disable()
                with (
                    ui.button("Open", icon="folder_open")
                    .props("flat")
                    .classes("lc-quiet-btn") as self.open_button
                ):
                    with ui.menu().props("anchor='bottom right' self='top right'"):
                        ui.menu_item("Open project", on_click=self.choose_folder)
                        ui.menu_item("Open example", on_click=self.open_example)
                gear = (
                    ui.button(icon="settings", on_click=lambda: self.tabs.set_value(SETTINGS))
                    .props("flat round")
                    .classes("lc-gear")
                    .tooltip("Settings")
                )
            with (
                ui.tabs(value="overview")
                .props("dense no-caps inline-label align=left active-color=primary")
                .classes("lc-nav mt-2") as tabs
            ):
                nav = {}
                for i, group in enumerate(PAGES):
                    if i:
                        ui.separator().props("vertical")
                    nav |= {name: ui.tab(name, label=label) for name, label in group}
                ui.tab(SETTINGS, label="Settings").classes("hidden")
                with nav["problems"]:
                    self.badge = ui.label().classes("lc-pill ml-2")
                    self.badge.visible = False
        self.tabs = tabs
        tabs.on_value_change(
            lambda e: gear.classes(**{"add" if e.value == SETTINGS else "remove": "lc-active"})
        )

        with ui.tab_panels(tabs, value="overview").classes("w-full bg-transparent"):
            with ui.tab_panel("overview").classes("lc-page"):
                self.overview_panel()
            with ui.tab_panel("instruments").classes("lc-page"):
                self.instruments_panel()
            with ui.tab_panel("studies").classes("lc-page"):
                self.studies_panel()
            with ui.tab_panel("datasets").classes("lc-page"):
                self.datasets_panel()
            with ui.tab_panel("analysis").classes("lc-page"):
                self.analysis_panel()
            with ui.tab_panel("methods").classes("lc-page"):
                self.methods_panel()
            with ui.tab_panel("prepare").classes("lc-page"):
                self.prepare_panel()
            with ui.tab_panel("import").classes("lc-page"):
                self.import_panel()
            with ui.tab_panel("edit").classes("lc-page"):
                self.edit_panel()
            with ui.tab_panel("problems").classes("lc-page"):
                self.problems_panel()
            with ui.tab_panel("settings").classes("lc-page"):
                settings.render(
                    self.set_appearance,
                    self.set_palette,
                    self.start_cfa,
                    self.instruments_panel.refresh,
                    self.reload,
                    self.set_decimals,
                    self.reset_example,
                )

    async def choose_folder(self) -> None:
        selection = await app.native.main_window.create_file_dialog(webview.FileDialog.FOLDER)
        if selection:
            self.home = None
            self.frozen_bar.visible = False
            await self.open_project(Path(selection[0]))

    async def open_project(self, root: Path) -> None:
        # Remembered for the next start; a freeze opened from it is not.
        preferences.save({preferences.LAST_PROJECT: str(root)})
        await self.load(root)

    async def open_example(self) -> None:
        self.home = None
        self.frozen_bar.visible = False
        await self.open_project(example.example_copy())

    async def reset_example(self) -> None:
        folder = example.reset_example()
        if self.root == folder:
            await self.load(folder)
        ui.notify("The example is back as installed")

    async def load(self, root: Path) -> None:
        self.set_busy(True)
        try:
            result = await common.computed(run_catalog, root)
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
                self.studying = StudiesView()
                self.analysis = AnalysisView()
                self.methods = MethodsView()
                self.importing = ImportView()
                self.editing = EditView()
                self.preparing = PrepareView()
                self.root = root
            self.set_busy(False)
        self.result = result
        self.show_result()
        # R is slow, so the factor models fill in after the rest of the catalog shows.
        background_tasks.create(self.start_cfa())

    async def open_freeze(self, name: str) -> None:
        datalad = preferences.load().get(preferences.DATALAD)
        if not datalad:
            ui.notify("Set the path to datalad on the Settings page first", type="warning")
            return
        self.set_busy(True)
        try:
            copy = await common.computed(run_open_freeze, self.root, name, datalad)
        except LabCatalogError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        finally:
            self.set_busy(False)
        record = next(f for f in list_freezes(self.root) if f.name == name)
        home = self.root
        await self.load(copy)
        self.home = home
        self.frozen_label.set_text(frozen_text(record, self.result))
        self.frozen_bar.visible = True
        self.datasets_panel.refresh()

    async def leave_freeze(self) -> None:
        home, self.home = self.home, None
        self.frozen_bar.visible = False
        await self.load(home)

    async def reload(self) -> None:
        if self.root is not None:
            await self.load(self.root)

    async def start_cfa(self) -> None:
        result, cfa = self.result, self.cfa
        rscript = preferences.load().get(preferences.RSCRIPT)
        cfa.fits, cfa.message = [], ""
        cfa.invariance, cfa.invariance_message = [], ""
        if result is None or result.project is None:
            cfa.status = cfa.invariance_status = CFA_UNSET
            cfa_changed()
            return
        cfa.status = CFA_RUNNING
        cfa.invariance_status = CFA_RUNNING if rscript else CFA_UNSET
        cfa_changed()
        fits, message, status = await in_r(run_cfa, result, rscript)
        if status == CFA_FAILED:
            fits = await common.computed(run_cfa, result, None)
            message, status = (
                f"R failed, so the factor models were fitted in Python: {message}",
                CFA_DONE,
            )
        # A newer Refresh has started its own run.
        if self.result is not result:
            return
        cfa.fits, cfa.message, cfa.status = fits, message, status
        cfa_changed()
        if not rscript:
            return
        found = await in_r(run_invariance, result, rscript)
        if self.result is not result:
            return
        cfa.invariance, cfa.invariance_message, cfa.invariance_status = found
        cfa_changed()

    async def set_appearance(self, name: str) -> None:
        preferences.save({preferences.APPEARANCE: name})
        self.dark_mode.set_value(theme.mode_value(name))
        if name == theme.SYSTEM:
            await self.follow_system()
            return
        theme.set_dark(name == theme.DARK)
        if self.result is not None:
            self.show_result()

    async def follow_system(self) -> None:
        # Figures are drawn on the server, which cannot see the system setting.
        on = await ui.run_javascript("window.matchMedia('(prefers-color-scheme: dark)').matches")
        theme.set_dark(bool(on))
        if self.result is not None:
            self.show_result()

    def set_palette(self, name: str) -> None:
        style.use_palette(name)
        preferences.save({preferences.PALETTE: name})
        if self.result is not None:
            self.show_result()

    def set_decimals(self, places: int) -> None:
        common.set_decimals(places)
        preferences.save({preferences.DECIMALS: places})
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
        self.badge.classes(replace=f"lc-pill ml-2 {'lc-bad' if failed else 'lc-warn'}")
        self.badge.visible = bool(issues)
        if result is not None and project is None:
            self.tabs.set_value("problems")
        for panel in (
            self.overview_panel,
            self.instruments_panel,
            self.studies_panel,
            self.datasets_panel,
            self.analysis_panel,
            self.methods_panel,
            self.prepare_panel,
            self.import_panel,
            self.edit_panel,
            self.problems_panel,
        ):
            panel.refresh()

    def open_instrument(self, instrument_id: str | None) -> None:
        self.view.instrument = instrument_id
        self.instruments_panel.refresh()
        self.tabs.set_value("instruments")

    def edit_location(self, path: str, line: int | None) -> None:
        self.tabs.set_value("edit")
        self.editing.open(path, line)

    async def dataset_added(self, dataset: str) -> None:
        ui.notify(f"Added {dataset}")
        self.dataset = dataset
        await self.reload()

    def show_dataset(self, dataset: str | None) -> None:
        self.dataset = dataset
        self.datasets_panel.refresh()

    @ui.refreshable_method
    def overview_panel(self) -> None:
        if self.has_catalog():
            overview.render(
                self.result,
                lambda: self.open_instrument(None),
                lambda: self.tabs.set_value("datasets"),
                lambda: self.tabs.set_value("problems"),
            )

    @ui.refreshable_method
    def instruments_panel(self) -> None:
        if self.has_catalog():
            instruments.render(self.result, self.index, self.view, self.open_instrument, self.cfa)

    @ui.refreshable_method
    def studies_panel(self) -> None:
        if self.has_catalog():
            studies.render(
                self.result, self.studying, self.reload, self.open_dataset, self.dataset_added
            )

    def open_dataset(self, dataset: str) -> None:
        self.show_dataset(dataset)
        self.tabs.set_value("datasets")

    @ui.refreshable_method
    def datasets_panel(self) -> None:
        if self.has_catalog():
            datasets.render(
                self.result,
                self.dataset,
                self.show_dataset,
                self.open_instrument,
                self.reload,
                None if self.home else self.open_freeze,
                self.edit_location,
                self.dataset_added,
            )

    @ui.refreshable_method
    def analysis_panel(self) -> None:
        if self.has_catalog():
            analysis.render(self.result, self.analysis)

    @ui.refreshable_method
    def methods_panel(self) -> None:
        if self.has_catalog():
            methods.render(self.result, self.methods, self.cfa)

    @ui.refreshable_method
    def prepare_panel(self) -> None:
        if self.root is None:
            common.empty("Open a project folder to run its prepare steps.", "folder_open")
        else:
            prepare.render(self.root, self.preparing, lambda: self.load(self.root))

    @ui.refreshable_method
    def edit_panel(self) -> None:
        if self.root is None:
            common.empty("Open a project folder to edit its files.", "folder_open")
        else:
            edit.render(self.root, self.editing, lambda: self.load(self.root))

    @ui.refreshable_method
    def import_panel(self) -> None:
        if self.has_catalog():
            codebook_import.render(self.result, self.importing, self.edit_location)

    @ui.refreshable_method
    def problems_panel(self) -> None:
        if self.result is None:
            common.empty(self.error or "Open a project folder to check it.", "folder_open")
        else:
            problems.render(
                self.result.report, self.root, self.edit_location, self.open_fix, self.reload
            )
        self.get_missing_button()

    def open_fix(self, issue: Issue) -> None:
        actions = fix.FixActions(
            lambda location: problems.follow(self.root, location, self.edit_location),
            self.reload,
            self.root,
            lambda template, wave: new_dataset.open_wizard(
                self.result, self.dataset_added, repeat=(template, wave)
            ),
        )
        fix.open_fix(self.result, issue, actions)

    def has_catalog(self) -> bool:
        if self.result is None:
            common.empty(self.error or "Open a project folder to see its catalog.", "folder_open")
        elif self.result.project is None:
            common.empty("The project files have errors. Fix them, then press Refresh.", "error")
        self.get_missing_button()
        return self.result is not None and self.result.project is not None

    def get_missing_button(self) -> None:
        # Files a clone has not downloaded yet stop the catalog from loading.
        failed = self.result is None or self.result.project is None
        if self.root is not None and failed and dataset_root(self.root):
            get_button("Get missing content", run_get_missing, [self.root], self.reload)


def cfa_changed() -> None:
    instruments.cfa_changed()
    methods.cfa_changed()


async def in_r(
    function: Callable[[CatalogResult, str | None], list],
    result: CatalogResult,
    rscript: str | None,
) -> tuple[list, str, str]:
    try:
        found = await common.computed(function, result, rscript)
    except LabCatalogError as err:
        return [], str(err), CFA_FAILED
    return found, "", CFA_DONE


def as_of_text(result: CatalogResult) -> str:
    if result.summary is None:
        return ""
    dates = sorted({d.snapshot_date for d in result.summary.datasets if d.snapshot_date})
    if not dates:
        return ""
    return f"Data as of {dates[0]}" + (f" to {dates[-1]}" if len(dates) > 1 else "")
