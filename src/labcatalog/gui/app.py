import secrets
import socket
from collections.abc import Callable
from functools import partial
from pathlib import Path

from nicegui import app, background_tasks, ui
from nicegui.native import find_open_port
from nicegui.storage import Storage

from labcatalog.charts import style, views
from labcatalog.data.manifest import changed, file_times
from labcatalog.datalad.annex import dataset_root
from labcatalog.datalad.bridge import use_folder
from labcatalog.datalad.freeze import list_freezes
from labcatalog.datalad.sync import dataset_states, project_datasets, summary
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import (
    analysis,
    codebook_import,
    codebook_step,
    common,
    datasets,
    edit,
    example,
    fix,
    gate,
    id_check,
    instruments,
    look,
    methods,
    new_dataset,
    overview,
    preferences,
    prepare,
    problems,
    serving,
    settings,
    setup,
    shared,
    studies,
    theme,
)
from labcatalog.gui.analysis import AnalysisView
from labcatalog.gui.codebook_import import ImportView
from labcatalog.gui.codebook_step import CodebookView
from labcatalog.gui.datalad import clone_dialog, frozen_text, get_button, versions_tooltip
from labcatalog.gui.datasets import DatasetsView
from labcatalog.gui.edit import EditView
from labcatalog.gui.files import FOLDER, choose_path
from labcatalog.gui.filter_bar import Filters
from labcatalog.gui.gate import Gate
from labcatalog.gui.instruments import (
    CFA_DONE,
    CFA_FAILED,
    CFA_RUNNING,
    CFA_UNSET,
    BrowseView,
    CfaView,
)
from labcatalog.gui.look import Look, register, within
from labcatalog.gui.methods import MethodsView
from labcatalog.gui.prepare import PrepareView
from labcatalog.gui.setup import SetupView
from labcatalog.gui.studies import StudiesView
from labcatalog.issues import Issue
from labcatalog.metadata import accepted
from labcatalog.metadata.browse import BrowseIndex, build_index
from labcatalog.paths import portable_path
from labcatalog.pipeline import (
    CatalogResult,
    run_cfa,
    run_get_missing,
    run_invariance,
    run_open_freeze,
)
from labcatalog.stats import rbridge
from labcatalog.version import __version__

WINDOW_SIZE = (1280, 820)
# Groups of pages, drawn with a line between them; Studies and Settings open from the header.
PAGES = (
    (("overview", "Overview"), ("instruments", "Instruments"), ("datasets", "Datasets")),
    (("analysis", "Analysis"), ("methods", "Methods")),
    # Set up's steps, numbered, all showing the one Set up page.
    tuple(setup.STEPS.items()),
    (("problems", "Problems"),),
)
SETUP = "setup"
SETTINGS = "settings"
STUDY = "studies"
# The study picker's choice that narrows nothing; a study ID never has this character.
ALL_STUDIES = "*"
# How often the window looks for files changed by someone else.
DISK_SECONDS = 5
LOCAL_HOST = "127.0.0.1"


def launch(
    project: Path | None = None,
    browser: bool = False,
    port: int | None = None,
    projects: Path | None = None,
    host: str = LOCAL_HOST,
) -> None:
    theme.install()
    look.install()
    if projects is not None:
        serve(projects)
        browser = True
    if datalad := preferences.load().get(preferences.DATALAD):
        use_folder(datalad)
    rbridge.allow_at_once(
        int(preferences.load().get(preferences.R_AT_ONCE, rbridge.DEFAULT_AT_ONCE))
    )
    app.on_shutdown(rbridge.stop_all)
    port = port or find_open_port()
    token = secrets.token_urlsafe(24)
    app.add_middleware(Gate, token=token, port=port)
    start = f"/?{gate.PARAMETER}={token}"
    options = {
        "root": lambda: main_page(project),
        "title": f"labcatalog {__version__}",
        "port": port,
        "favicon": theme.ICON,
        "reload": False,
        "show_welcome_message": False,
    }
    if browser:
        common.native = False
        shown = LOCAL_HOST if host == LOCAL_HOST else socket.gethostname()
        print(f"labcatalog is at http://{shown}:{port}{start}")
        if common.serving:
            print(f"It serves the projects in {common.serving} to everyone with that link.")
        if host != LOCAL_HOST:
            print(
                "Anyone on the network with the link can open these projects and run their "
                "prepare steps, and the link travels unencrypted (no HTTPS): put a reverse proxy "
                "with HTTPS in front, or reach it through an SSH tunnel instead."
            )
        print("Open that link in a browser; this stops when you press Ctrl+C.", flush=True)
        if common.serving:
            options["storage_secret"] = preferences.server_secret()
        ui.run(host=host, show=start if not common.serving else False, **options)
        return
    # Saving a table or figure goes through the window's own save dialog.
    app.native.settings["ALLOW_DOWNLOADS"] = True
    app.native.window_args["url"] = f"http://127.0.0.1:{port}{start}"
    ui.run(native=True, window_size=WINDOW_SIZE, **options)


def main_page(project: Path | None) -> None:
    # A packaged app has no console, so unexpected errors must show up in the window.
    ui.on_exception(
        lambda err: ui.notify(
            f"Unexpected error: {err!r}", type="negative", multi_line=True, timeout=0
        )
    )
    window = Window()
    window.build()
    if common.serving:
        ui.timer(0, window.start_serving, once=True)
        return
    start = project.resolve() if project is not None else example.start_folder()
    ui.timer(0, lambda: window.open_project(start), once=True)


def serve(projects: Path) -> None:
    # One labcatalog for several people: each person's own settings and name go with their browser.
    common.serving = projects.resolve()
    Storage.path = preferences.folder() / "browsers"
    preferences.browser = lambda: app.storage.user
    accepted.named = lambda: look.look().who


class Window:
    def __init__(self) -> None:
        saved = preferences.mine().get(preferences.PALETTE)
        # A palette saved by another version may no longer exist.
        self.look = Look(palette=saved if saved in style.PALETTES else style.DEFAULT_PALETTE)
        self.look.who = preferences.mine().get(preferences.WHO)
        register(ui.context.client, self.look)
        self.root: Path | None = None
        self.result: CatalogResult | None = None
        self.index: BrowseIndex | None = None
        self.view = BrowseView()
        self.studying = StudiesView()
        self.datasets_view = DatasetsView()
        self.problem_filters = Filters()
        self.analysis = AnalysisView()
        self.methods = MethodsView()
        self.importing = ImportView()
        self.codebook = CodebookView()
        self.editing = EditView()
        self.preparing = PrepareView()
        self.setting_up = SetupView()
        self.step_marks: dict[str, ui.label] = {}
        self.step_tips: dict[str, ui.tooltip] = {}
        self.steps: dict[str, ui.column] = {}
        self.cfa = CfaView(
            open_settings=lambda: self.tabs.set_value("settings"),
            reload=self.reload,
            refit=self.fit_factor_models,
            retest=self.test_invariance,
        )
        self.dataset: str | None = None
        # The study the pages are narrowed to, None for every study.
        self.scope: str | None = None
        self.error: str | None = None
        # The project a frozen copy was opened from, while the copy is shown.
        self.home: Path | None = None
        # When each file was last changed as the catalog read it.
        self.times: dict[Path, int] = {}
        self.watching = False

    def build(self) -> None:
        appearance = preferences.mine().get(preferences.APPEARANCE, theme.DEFAULT_APPEARANCE)
        # A value saved by another version may no longer exist.
        appearance = appearance if appearance in theme.APPEARANCES else theme.DEFAULT_APPEARANCE
        self.dark_mode = ui.dark_mode(theme.mode_value(appearance))
        self.look.dark = appearance == theme.DARK
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
                self.disk_mark = ui.label("Changed on disk").classes(
                    "lc-pill lc-info cursor-pointer"
                )
                with self.disk_mark:
                    self.disk_tip = ui.tooltip("")
                self.disk_mark.on("click", self.reload)
                self.disk_mark.visible = False
                self.example_mark = ui.label("Example updated").classes(
                    "lc-pill lc-warn cursor-pointer"
                )
                with self.example_mark:
                    ui.tooltip(
                        "The example has changed since this copy was made; click to reset the "
                        "copy to the new version"
                    )
                self.example_mark.on("click", self.confirm_reset_example)
                self.example_mark.visible = False
                self.data_mark = ui.label().classes("lc-pill cursor-pointer")
                with self.data_mark:
                    self.data_tip = ui.tooltip("")
                self.data_mark.on("click", self.open_versions)
                self.data_mark.visible = False
                self.scope_select = (
                    ui.select({}, on_change=lambda e: self.set_scope(e.value))
                    .props("dense outlined options-dense")
                    .classes("lc-scope")
                    .tooltip("The study the pages show")
                )
                self.scope_select.visible = False
                self.study_button = (
                    ui.button(
                        "Studies", icon="list_alt", on_click=lambda: self.tabs.set_value(STUDY)
                    )
                    .props("flat no-caps")
                    .classes("lc-quiet-btn")
                    .tooltip("Each study's details, waves and text")
                )
                self.study_button.visible = False
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
                        ui.menu_item("Clone a project", on_click=self.clone_project)
                        if not common.serving:
                            ui.menu_item("Open example", on_click=self.open_example)
                if common.serving:
                    self.who_button = (
                        ui.button(self.look.who or "", icon="person", on_click=self.rename)
                        .props("flat no-caps")
                        .classes("lc-quiet-btn")
                        .tooltip("Your name, on what you change")
                    )
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
                    for name, label in group:
                        if name in setup.STEPS:
                            nav[name] = self.step_tab(name, label)
                        else:
                            nav[name] = ui.tab(name, label=label)
                ui.tab(SETTINGS, label="Settings").classes("hidden")
                ui.tab(STUDY, label="Studies").classes("hidden")
                with nav["problems"]:
                    self.badge = ui.label().classes("lc-pill ml-2")
                    self.badge.visible = False
        self.tabs = tabs
        ui.timer(DISK_SECONDS, self.watch_disk)
        tabs.on_value_change(lambda e: self.show_page(gear, e.value))

        with ui.tab_panels(value="overview").classes("w-full bg-transparent") as self.pages:
            with ui.tab_panel("overview").classes("lc-page"):
                self.overview_panel()
            with ui.tab_panel("instruments").classes("lc-page"):
                self.instruments_panel()
            with ui.tab_panel(STUDY).classes("lc-page"):
                self.studies_panel()
            with ui.tab_panel("datasets").classes("lc-page"):
                self.datasets_panel()
            with ui.tab_panel("analysis").classes("lc-page"):
                self.analysis_panel()
            with ui.tab_panel("methods").classes("lc-page"):
                self.methods_panel()
            with ui.tab_panel(SETUP).classes("lc-page"):
                # Every step stays built, so an unsaved edit survives a look at another step.
                for name, parts in (
                    (setup.CODEBOOK, (self.codebook_panel, self.edit_panel)),
                    (setup.DATA, (self.add_data_panel, self.prepare_panel, self.import_panel)),
                    (setup.IDS, (self.ids_panel,)),
                ):
                    with ui.column().classes("lc-step w-full") as self.steps[name]:
                        for part in parts:
                            part()
                        setup.next_button(name, self.pick_step)
                self.show_step()
            with ui.tab_panel("problems").classes("lc-page"):
                self.problems_panel()
            with ui.tab_panel("settings").classes("lc-page"):
                self.project_settings = settings.render(
                    lambda: self.result,
                    self.set_appearance,
                    self.set_palette,
                    self.start_cfa,
                    self.instruments_panel.refresh,
                    self.reload,
                    self.reset_example,
                )

    async def start_serving(self) -> None:
        if not self.look.who:
            await self.rename()
        start = serving.start_folder()
        if start is None:
            await self.choose_folder()
        else:
            await self.open_project(start)

    async def rename(self) -> None:
        await serving.ask_name(self.look)
        self.who_button.set_text(self.look.who)

    async def choose_folder(self) -> None:
        if common.serving:
            folder = await serving.choose_project(self.root)
        else:
            start = self.root.parent if self.root is not None else None
            folder = await choose_path(FOLDER, start=start)
        if folder:
            self.home = None
            self.frozen_bar.visible = False
            await self.open_project(folder)

    async def clone_project(self) -> None:
        root = await clone_dialog(self.root.parent if self.root is not None else None)
        if root:
            self.home = None
            self.frozen_bar.visible = False
            await self.open_project(root)

    async def open_project(self, root: Path) -> None:
        # Remembered for the next start; a freeze opened from it is not.
        preferences.save_mine({preferences.LAST_PROJECT: str(root)})
        await self.load(root)

    async def open_example(self) -> None:
        self.home = None
        self.frozen_bar.visible = False
        await self.open_project(example.example_copy())

    def confirm_reset_example(self) -> None:
        settings.confirm_reset(self.reset_example)

    async def reset_example(self) -> None:
        folder = example.reset_example()
        if self.root == folder:
            await self.load(folder)
        ui.notify("The example is back as installed")

    async def load(self, root: Path) -> None:
        self.set_busy(True)
        try:
            times, result = await common.computed(shared.catalog, root)
        except LabCatalogError as err:
            # The project stays open so Set up can make the missing data.
            ui.notify(str(err), type="negative", multi_line=True)
            result, self.error = None, str(err)
        else:
            self.error = None
        finally:
            # Refreshing keeps the filters; opening another project starts over.
            if root != self.root:
                self.view = BrowseView()
                self.studying = StudiesView()
                self.datasets_view = DatasetsView()
                self.problem_filters = Filters()
                self.analysis = AnalysisView()
                self.methods = MethodsView()
                self.importing = ImportView()
                self.codebook = CodebookView()
                self.editing = EditView()
                self.preparing = PrepareView()
                self.setting_up = SetupView()
                self.cfa.estimator = self.cfa.invariance_estimator = None
                self.root = root
                self.scope = preferences.mine().get(preferences.STUDY_SCOPE, {}).get(str(root))
                self.follow_scope()
            self.set_busy(False)
        self.result, self.times = result, times
        self.disk_mark.visible = False
        self.show_result()
        # R is slow, so the factor models fill in after the rest of the catalog shows.
        background_tasks.create(within(self.look, self.start_cfa()))

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
        cfa.fits, cfa.message = [], ""
        cfa.invariance, cfa.invariance_message = [], ""
        if result is None or result.project is None:
            cfa.status = cfa.invariance_status = CFA_UNSET
            cfa_changed(cfa)
            return
        rscript = preferences.load().get(preferences.RSCRIPT)
        cfa.invariance_status = CFA_RUNNING if rscript else CFA_UNSET
        await self.fit_factor_models()
        if rscript and self.result is result:
            await self.test_invariance()

    async def fit_factor_models(self) -> None:
        result, cfa = self.result, self.cfa
        rscript = preferences.load().get(preferences.RSCRIPT)
        fit = partial(run_cfa, estimator=cfa.estimator or default_estimator(result))
        cfa.fits, cfa.message, cfa.status = [], "", CFA_RUNNING
        cfa_changed(cfa)
        fits, message, status = await in_r(fit, result, rscript)
        if status == CFA_FAILED:
            fits = await common.computed(shared.fitted, fit, result, None)
            message, status = (
                f"R failed, so the factor models were fitted in Python: {message}",
                CFA_DONE,
            )
        # A newer Refresh has started its own run.
        if self.result is not result:
            return
        cfa.fits, cfa.message, cfa.status = fits, message, status
        cfa_changed(cfa)

    async def test_invariance(self) -> None:
        result, cfa = self.result, self.cfa
        rscript = preferences.load().get(preferences.RSCRIPT)
        test = partial(
            run_invariance, estimator=cfa.invariance_estimator or default_estimator(result)
        )
        cfa.invariance, cfa.invariance_message, cfa.invariance_status = [], "", CFA_RUNNING
        cfa_changed(cfa)
        found = await in_r(test, result, rscript)
        if self.result is not result:
            return
        cfa.invariance, cfa.invariance_message, cfa.invariance_status = found
        cfa_changed(cfa)

    async def set_appearance(self, name: str) -> None:
        preferences.save_mine({preferences.APPEARANCE: name})
        self.dark_mode.set_value(theme.mode_value(name))
        if name == theme.SYSTEM:
            await self.follow_system()
            return
        self.look.dark = name == theme.DARK
        if self.result is not None:
            self.show_result()

    async def follow_system(self) -> None:
        # Figures are drawn on the server, which cannot see the system setting.
        on = await ui.run_javascript("window.matchMedia('(prefers-color-scheme: dark)').matches")
        self.look.dark = bool(on)
        if self.result is not None:
            self.show_result()

    def set_palette(self, name: str) -> None:
        self.look.palette = name
        preferences.save_mine({preferences.PALETTE: name})
        if self.result is not None:
            self.show_result()

    def set_busy(self, busy: bool) -> None:
        self.spinner.visible = busy
        self.open_button.set_enabled(not busy)
        self.refresh_button.set_enabled(not busy and self.root is not None)

    def show_result(self) -> None:
        result = self.result
        project = result.project if result else None
        self.look.use_project(project.config if project else None)
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
        self.show_scope()
        self.example_mark.visible = example.outdated(self.root)
        self.data_mark.visible = False
        if project is not None and self.home is None:
            background_tasks.create(within(self.look, self.show_versions()))
        for panel in (
            self.overview_panel,
            self.instruments_panel,
            self.studies_panel,
            self.datasets_panel,
            self.analysis_panel,
            self.methods_panel,
            self.codebook_panel,
            self.add_data_panel,
            self.prepare_panel,
            self.ids_panel,
            self.import_panel,
            self.edit_panel,
            self.problems_panel,
        ):
            panel.refresh()
        self.show_counts()
        self.project_settings()

    async def show_versions(self) -> None:
        # Only with datalad set: inside a dataset git itself needs git-annex on PATH.
        root = self.root
        if not preferences.load().get(preferences.DATALAD):
            return
        roots = project_datasets(self.result.project.config, root.resolve())
        if not roots:
            return
        states = await common.computed(dataset_states, roots)
        if root != self.root:
            return
        text, kind = summary(states)
        self.data_mark.set_text(text)
        self.data_mark.classes(replace=f"lc-pill cursor-pointer lc-{kind}")
        self.data_tip.set_text(versions_tooltip(states, root))
        self.data_mark.visible = True

    async def watch_disk(self) -> None:
        # Someone else's save, or a synced folder, changes the files under this window.
        if self.root is None or self.home is not None or self.spinner.visible or self.watching:
            return
        root, times = self.root, self.times
        self.watching = True
        try:
            now = await common.computed(file_times, root)
        finally:
            self.watching = False
        if root != self.root or times is not self.times:
            return
        found = changed(times, now)
        self.disk_mark.visible = bool(found)
        names = ", ".join(portable_path(p, root).as_posix() for p in found)
        self.disk_tip.set_text(
            f"Changed since the project was read: {names}. Click to read it again."
        )

    def open_versions(self) -> None:
        self.show_dataset(None)
        self.tabs.set_value("datasets")

    def show_scope(self) -> None:
        studies = self.result.project.config.studies if self.result and self.result.project else {}
        if self.scope not in studies:
            self.scope = None
        options = {ALL_STUDIES: "All studies"} | {s: c.label or s for s, c in studies.items()}
        self.scope_select.set_options(options, value=self.scope or ALL_STUDIES)
        shown = self.result is not None and self.result.project is not None
        self.scope_select.visible = self.study_button.visible = shown

    def mark_header(self, gear: ui.button, page: str) -> None:
        for button, mine in ((gear, SETTINGS), (self.study_button, STUDY)):
            button.classes(**{"add" if page == mine else "remove": "lc-active"})

    async def studies_saved(self, old: str | None = None, new: str | None = None) -> None:
        # The pages keep showing a study the Studies page renamed.
        if old is not None and old == self.scope:
            self.scope = new
            saved = preferences.mine().get(preferences.STUDY_SCOPE, {})
            preferences.save_mine({preferences.STUDY_SCOPE: {**saved, str(self.root): new}})
            self.follow_scope()
        await self.reload()

    def set_scope(self, value: str) -> None:
        scope = None if value == ALL_STUDIES else value
        if scope == self.scope:
            return
        if self.studying.edited:
            self.confirm_scope(scope)
            return
        self.scope = scope
        saved = preferences.mine().get(preferences.STUDY_SCOPE, {})
        preferences.save_mine({preferences.STUDY_SCOPE: {**saved, str(self.root): scope}})
        self.follow_scope()
        for panel in (
            self.overview_panel,
            self.instruments_panel,
            self.studies_panel,
            self.datasets_panel,
            self.analysis_panel,
            self.methods_panel,
        ):
            panel.refresh()

    def confirm_scope(self, scope: str | None) -> None:
        # Narrowing the pages draws the Studies page again, which would drop its unsaved changes.
        def discard() -> None:
            dialog.close()
            self.studying.edited = False
            self.set_scope(scope or ALL_STUDIES)

        def keep() -> None:
            dialog.close()
            self.scope_select.set_value(self.scope or ALL_STUDIES)

        with ui.dialog().props("persistent") as dialog, ui.card():
            ui.label(f"Discard your changes to {self.studying.study}?")
            with ui.row():
                ui.button("Discard", on_click=discard)
                ui.button("Keep editing", on_click=keep).props("flat")
        dialog.open()

    def follow_scope(self) -> None:
        # The pages that keep their own choice of study start from the one picked at the top.
        if self.scope is None:
            self.view.selected.pop("study", None)
            self.datasets_view.filters.selected.pop("study", None)
            self.problem_filters.selected.pop("study", None)
            return
        self.view.selected["study"] = {self.scope}
        self.datasets_view.filters.selected["study"] = {self.scope}
        self.problem_filters.selected["study"] = {self.scope}
        self.studying.study = self.scope
        self.methods.study = self.scope

    def open_instrument(self, instrument_id: str | None) -> None:
        self.view.instrument = instrument_id
        self.instruments_panel.refresh()
        self.tabs.set_value("instruments")

    def edit_location(self, path: str, line: int | None) -> None:
        self.tabs.set_value(setup.CODEBOOK)
        self.editing.open(path, line)

    def pick_step(self, name: str) -> None:
        if name == setup.REVIEW:
            self.datasets_view.layout = datasets.REVIEW
            self.show_dataset(None)
            name = "datasets"
        self.tabs.set_value(name)

    def show_page(self, gear: ui.button, page: str) -> None:
        self.mark_header(gear, page)
        if page in setup.STEPS:
            self.setting_up.step = page
            self.show_step()
        self.pages.set_value(SETUP if page in setup.STEPS else page)

    def show_step(self) -> None:
        for name, part in self.steps.items():
            part.visible = name == self.setting_up.step

    def step_tab(self, name: str, label: str) -> ui.tab:
        with ui.tab(name, label="") as tab:
            ui.label(str(list(setup.STEPS).index(name) + 1)).classes("lc-step-num")
            ui.label(label).classes("q-tab__label")
            with ui.label().classes("lc-pill lc-warn ml-2") as self.step_marks[name]:
                self.step_tips[name] = ui.tooltip("")
            self.step_marks[name].visible = False
        return tab

    def show_counts(self) -> None:
        found = setup.counts(self.result)
        texts = setup.to_do(self.result)
        for name, mark in self.step_marks.items():
            mark.set_text(str(sum(found.get(name, {}).values())))
            self.step_tips[name].set_text(texts.get(name, ""))
            mark.visible = bool(found.get(name))

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
                views.for_study(self.result, self.scope),
                lambda: self.open_instrument(None),
                lambda: self.tabs.set_value("datasets"),
                lambda: self.tabs.set_value("problems"),
                self.open_map,
            )

    def open_map(self) -> None:
        self.view.layout = instruments.MAP
        self.open_instrument(None)

    @ui.refreshable_method
    def instruments_panel(self) -> None:
        if self.has_catalog():
            instruments.render(self.result, self.index, self.view, self.open_instrument, self.cfa)

    @ui.refreshable_method
    def studies_panel(self) -> None:
        if self.has_catalog():
            studies.render(
                self.result,
                self.studying,
                self.studies_saved,
                self.open_dataset,
                self.dataset_added,
            )

    def open_dataset(self, dataset: str) -> None:
        self.show_dataset(dataset)
        self.tabs.set_value("datasets")

    @ui.refreshable_method
    def datasets_panel(self) -> None:
        if self.has_catalog():
            datasets.render(
                self.result,
                self.datasets_view,
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
            analysis.render(self.result, self.analysis, self.scope, self.reload)

    @ui.refreshable_method
    def methods_panel(self) -> None:
        if self.has_catalog():
            methods.render(self.result, self.methods, self.cfa, self.scope)

    @ui.refreshable_method
    def codebook_panel(self) -> None:
        if self.result is None:
            common.empty(self.error or "Open a project folder to describe its instruments.")
            return
        codebook_step.render(
            self.result.project,
            self.codebook,
            self.edit_location,
            self.reload,
        )

    @ui.refreshable_method
    def add_data_panel(self) -> None:
        if not self.has_catalog():
            return
        with ui.row().classes("lc-panel lc-bar w-full items-center no-wrap gap-4"):
            common.panel_title(
                "Add a data file",
                "",
                "Copies a file into the project and links its columns to the instruments' items.",
            )
            if self.result.project.config.studies:
                ui.button(
                    "Add a data file",
                    icon="add",
                    on_click=lambda: new_dataset.open_wizard(self.result, self.dataset_added),
                ).props("no-caps").classes("shrink-0")
            else:
                common.note("Add a study on the Studies page first.")

    @ui.refreshable_method
    def prepare_panel(self) -> None:
        if self.root is None:
            common.empty("Open a project folder to run its prepare steps.", "folder_open")
        else:
            prepare.render(self.root, self.result, self.preparing, lambda: self.load(self.root))

    @ui.refreshable_method
    def edit_panel(self) -> None:
        if self.root is None:
            common.empty("Open a project folder to edit its files.", "folder_open")
        else:
            edit.render(self.root, self.editing, lambda: self.load(self.root))

    @ui.refreshable_method
    def ids_panel(self) -> None:
        if self.has_catalog():
            id_check.render(self.result, self.reload, lambda: self.pick_step("problems"))

    @ui.refreshable_method
    def import_panel(self) -> None:
        if self.has_catalog():
            codebook_import.render(self.result, self.importing, self.edit_location)

    @ui.refreshable_method
    def problems_panel(self) -> None:
        if self.result is None:
            common.empty(self.error or "Open a project folder to check it.", "folder_open")
        else:
            project = self.result.project
            problems.render(
                self.result.report,
                project.config if project else None,
                datasets.issue_datasets(self.result),
                self.problem_filters,
                self.root,
                self.edit_location,
                self.open_fix,
                self.reload,
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


def cfa_changed(cfa: CfaView) -> None:
    instruments.cfa_changed(cfa)
    methods.cfa_changed(cfa)


def default_estimator(result: CatalogResult) -> str:
    return result.project.config.stats.cfa_estimator


async def in_r(
    function: Callable[[CatalogResult, str | None], list],
    result: CatalogResult,
    rscript: str | None,
) -> tuple[list, str, str]:
    try:
        found = await common.computed(shared.fitted, function, result, rscript)
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
