import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

from nicegui import run, ui

from labcatalog.ai.cleaning import RAW_ROWS, ROWS, VALUES
from labcatalog.charts import style
from labcatalog.config import CORRELATIONS
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common, datalad, example, preferences, serving, theme
from labcatalog.gui.common import command, computed, note, panel, path_input, show_status
from labcatalog.gui.look import look
from labcatalog.llm import KEY_ENV, PROVIDERS
from labcatalog.metadata.editing import save_settings
from labcatalog.pipeline import CatalogResult
from labcatalog.stats import attrition, imputation, rbridge
from labcatalog.stats.cfa import ESTIMATORS
from labcatalog.stats.custom import PYTHON_PACKAGES, python_status
from labcatalog.stats.mediation import DEFAULT_WORKERS
from labcatalog.stats.rbridge import ALL_PACKAGES, install_command, r_status

# Where each program usually is on this kind of computer, shown under its path box.
RSCRIPT_EXAMPLE = {
    "win32": r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe",
    "darwin": "/usr/local/bin/Rscript",
}.get(sys.platform, "/usr/bin/Rscript")
MPLUS_EXAMPLE = {
    "win32": r"C:\Program Files\Mplus\Mplus.exe",
    "darwin": "/Applications/Mplus/mplus",
}.get(sys.platform, "/opt/mplus/mplus")
PYTHON_EXAMPLE = {
    "win32": r"C:\Users\you\AppData\Local\Programs\Python\Python313\python.exe",
    "darwin": "/usr/local/bin/python3",
}.get(sys.platform, "/usr/bin/python3")


def render(
    current: Callable[[], CatalogResult | None],
    on_appearance: Callable[[str], Awaitable[None]],
    on_palette: Callable[[str], None],
    on_rscript: Callable[[], Awaitable[None]],
    on_model: Callable[[], None],
    on_saved: Callable[[], Awaitable[None]],
    on_reset_example: Callable[[], Awaitable[None]],
) -> Callable[[], None]:
    # Returns what redraws the parts that follow the open project.
    with ui.row().classes("w-full no-wrap items-start gap-4"):
        with ui.column().classes("grow min-w-0 gap-4"):
            ui.label("This project").classes("lc-caption m-0")
            project = ui.refreshable(project_section)
            project(current, on_saved)
            ui.label("This computer").classes("lc-caption m-0")
            model = ui.refreshable(models_section)
            if common.serving:
                serving.server_section()
            else:
                r_section(on_rscript)
                mplus_section()
                python_section()
                datalad.datalad_section(on_saved)
                model(on_model)
        with ui.column().classes("w-96 shrink-0 gap-4"):
            ui.label("Only for you").classes("lc-caption m-0")
            looks_section(on_appearance, on_palette)
            tables_section()
            if not common.serving:
                example_section(on_reset_example)
    return lambda: (project.refresh(), model.refresh())


def project_section(
    current: Callable[[], CatalogResult | None], on_saved: Callable[[], Awaitable[None]]
) -> None:
    result = current()
    with panel(
        "Shared with the lab",
        "Saved in labcatalog.yaml, so everyone who opens the project starts from the same "
        "choices. Each section of the Analysis page can still try another for itself.",
    ):
        if result is None or result.project is None:
            note("Open a project that reads without errors to set its choices.")
            return
        config = result.project.config
        stats = config.stats
        with ui.row().classes("w-full items-start gap-2"):
            decimals = select(
                {places: str(places) for places in range(1, 5)},
                stats.decimals,
                "Decimal places (p values keep three)",
            )
            t_test = select(attrition.T_TESTS, stats.t_test, "Two groups")
            correlation = select(CORRELATIONS, stats.correlation, "Correlations")
            estimator = select(ESTIMATORS, stats.cfa_estimator, "Factor models")
        with ui.row().classes("w-full items-start gap-2"):
            missing = select(imputation.METHODS, stats.missing, "Missing values")
            imputations = (
                ui.number("Imputed data sets", value=stats.imputations, min=2, max=500, precision=0)
                .props("outlined dense")
                .classes("w-60")
            )
            seed = (
                ui.number("Imputation seed", value=stats.seed, precision=0)
                .props("outlined dense")
                .classes("w-60")
            )
        with ui.row().classes("w-full items-start gap-2"):
            provider = select(PROVIDERS, config.llm.provider, "Language model provider")
            raw_data = select(
                {VALUES: "Each column's values", ROWS: f"The first {RAW_ROWS} rows"},
                config.llm.raw_data,
                "What a cleaning script's model sees of a raw file",
            )
            model = (
                ui.input("Model", value=config.llm.model or "")
                .props("outlined dense")
                .classes("w-60")
            )
            ui.button("Save", on_click=lambda: save())
        status = ui.label()
        status.visible = False

        async def save() -> None:
            changes = {
                "stats": {
                    "decimals": decimals.value,
                    "t_test": t_test.value,
                    "correlation": correlation.value,
                    "cfa_estimator": estimator.value,
                    "missing": missing.value,
                    "imputations": int(imputations.value or stats.imputations),
                    "seed": int(stats.seed if seed.value is None else seed.value),
                },
                "llm": {
                    "provider": provider.value,
                    "model": (model.value or "").strip() or None,
                    "raw_data": raw_data.value,
                },
            }
            try:
                await run.io_bound(save_settings, result.project.root, changes)
            except LabCatalogError as err:
                show_status(status, str(err), "bad")
                return
            await on_saved()


def select(options: dict, value, label: str) -> ui.select:
    return ui.select(options, value=value, label=label).props("outlined dense").classes("w-60")


def r_section(on_rscript: Callable[[], Awaitable[None]]) -> None:
    with panel("R", "Factor models, ω and the Analysis page"):
        note(
            "Factor models (CFA) and ω run in R with lavaan and semTools, and the Analysis page "
            "uses R first, with psych and effectsize, and lme4, lmerTest and performance for "
            "the multilevel model; without R they use Python, except invariance across waves, "
            "which needs R. Install R and the packages yourself; this installs the packages "
            "when typed in R:"
        )
        command(install_command(ALL_PACKAGES))
        with ui.row().classes("w-full items-start no-wrap gap-2 mt-1"):
            path = path_input(
                "Rscript",
                preferences.load().get(preferences.RSCRIPT, ""),
                f"In R's bin folder, for example {RSCRIPT_EXAMPLE}",
            )
            button = ui.button("Save and check")
        status = ui.label()
        status.visible = False
        ui.select(
            {n: str(n) for n in range(1, 9)},
            value=int(preferences.load().get(preferences.BOOTSTRAP_WORKERS, DEFAULT_WORKERS)),
            label="R processes for bootstrap resamples (mediation)",
            on_change=lambda e: preferences.save({preferences.BOOTSTRAP_WORKERS: e.value}),
        ).props("outlined dense").classes("w-96 mt-2").tooltip(
            "More processes finish sooner; the resamples drawn differ with the number, so the "
            "intervals can move in the last digit"
        )

        def set_at_once(count: int) -> None:
            preferences.save({preferences.R_AT_ONCE: count})
            rbridge.allow_at_once(count)

        ui.select(
            {n: str(n) for n in range(1, 9)},
            value=int(preferences.load().get(preferences.R_AT_ONCE, rbridge.DEFAULT_AT_ONCE)),
            label="Analyses in R at once",
            on_change=lambda e: set_at_once(e.value),
        ).props("outlined dense").classes("w-96 mt-2").tooltip(
            "Further analyses wait their turn, so several windows cannot fill the memory"
        )

        async def save() -> None:
            # Windows' "Copy as path" wraps the path in quotes.
            value = (path.value or "").strip().strip('"')
            path.value = value
            preferences.save({preferences.RSCRIPT: value})
            if not value:
                show_status(
                    status,
                    "No Rscript set: no factor models, and the Analysis page uses Python.",
                    "warn",
                )
                await on_rscript()
                return
            show_status(status, "Checking R", "info")
            try:
                found = await computed(r_status, value)
            except LabCatalogError as err:
                show_status(status, str(err), "bad")
                return
            if found.missing:
                show_status(
                    status,
                    f"{found.version}, but it is missing {', '.join(found.missing)}; "
                    f"install them in R with: {install_command(found.missing)}",
                    "warn",
                )
            else:
                show_status(status, f"{found.version}, with every package labcatalog uses.", "ok")
            await on_rscript()

        button.on_click(save)
        path.on("keydown.enter", save)


def mplus_section() -> None:
    with panel("Mplus", "Factor models as Mplus inputs"):
        note(
            "Save to outputs under a factor model's tables also writes each model as an Mplus "
            "input (.inp) with its data (.dat). With the path to Mplus set here, a Run in Mplus "
            "button runs them; the results are in the .out files beside them. The numbers on the "
            "pages still come from R or Python."
        )
        with ui.row().classes("w-full items-start no-wrap gap-2 mt-1"):
            path = path_input(
                "Mplus",
                preferences.load().get(preferences.MPLUS, ""),
                f"The Mplus program, for example {MPLUS_EXAMPLE}",
            )
            button = ui.button("Save and check")
        status = ui.label()
        status.visible = False

        def save() -> None:
            value = (path.value or "").strip().strip('"')
            path.value = value
            preferences.save({preferences.MPLUS: value})
            if not value:
                show_status(status, "No Mplus set: inputs are written but not run.", "warn")
            elif Path(value).is_file():
                show_status(status, "Found Mplus.", "ok")
            else:
                show_status(status, f"No file at {value}.", "bad")

        button.on_click(save)
        path.on("keydown.enter", save)


def python_section() -> None:
    with panel("Python", "For custom analyses written in Python"):
        note(
            "The Custom tab of the Analysis page runs Python scripts with this Python, which "
            f"needs {', '.join(PYTHON_PACKAGES)}, and so do prepare steps that call python. Left "
            "empty, labcatalog uses its own Python, which has those packages; set one here to "
            "use packages of your own."
        )
        with ui.row().classes("w-full items-start no-wrap gap-2 mt-1"):
            path = path_input(
                "Python",
                preferences.load().get(preferences.PYTHON, ""),
                f"The Python program, for example {PYTHON_EXAMPLE}",
            )
            button = ui.button("Save and check")
        status = ui.label()
        status.visible = False

        async def save() -> None:
            value = (path.value or "").strip().strip('"')
            path.value = value
            preferences.save({preferences.PYTHON: value})
            chosen = preferences.python()
            try:
                found = await computed(python_status, chosen)
            except LabCatalogError as err:
                show_status(status, str(err), "bad")
                return
            if found.missing:
                show_status(
                    status,
                    f"Python {found.version}, but it is missing {', '.join(found.missing)}; "
                    f"install them with: pip install {' '.join(found.missing)}",
                    "warn",
                )
            else:
                show_status(status, f"Python {found.version}, with every package it needs.", "ok")

        button.on_click(save)
        path.on("keydown.enter", save)


def looks_section(
    on_appearance: Callable[[str], Awaitable[None]], on_palette: Callable[[str], None]
) -> None:
    with panel("Appearance"):
        ui.toggle(
            theme.APPEARANCES,
            value=preferences.mine().get(preferences.APPEARANCE, theme.DEFAULT_APPEARANCE),
            on_change=lambda e: on_appearance(e.value),
        ).props("no-caps")
        ui.select(
            {name: p.label for name, p in style.PALETTES.items()},
            value=look().palette,
            label="Chart colors",
            on_change=lambda e: on_palette(e.value),
        ).props("outlined dense").classes("w-full mt-2")


def tables_section() -> None:
    with panel(
        "Tables",
        "The Copy button under each table on the Analysis page copies it as a three-line "
        "table, as rich text for Word or Google Docs or as LaTeX (booktabs). Saving to outputs "
        "always writes each table as .csv, .docx and .tex.",
    ):
        ui.toggle(
            {preferences.RICH: "Word or Google Docs", preferences.LATEX: "LaTeX"},
            value=preferences.mine().get(preferences.TABLE_FORMAT, preferences.RICH),
            on_change=lambda e: preferences.save_mine({preferences.TABLE_FORMAT: e.value}),
        ).props("no-caps")


def example_section(on_reset_example: Callable[[], Awaitable[None]]) -> None:
    def confirm_reset() -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label("Reset the example? Every change made to it is lost.")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")

                async def reset() -> None:
                    dialog.close()
                    await on_reset_example()

                ui.button("Reset", on_click=reset).props("color=negative")
        dialog.open()

    with panel(
        "Example project",
        "The window opens the project that was open when it last closed, or the example the "
        f"first time. The example is a copy in {example.example_folder()}, so changes made "
        "while trying it out stay there; Reset puts it back as installed.",
    ):
        ui.button("Reset the example", icon="restart_alt", on_click=confirm_reset).props(
            "flat"
        ).classes("lc-quiet-btn w-fit")


def models_section(on_model: Callable[[], None]) -> None:
    provider = common.llm().provider
    with panel("Language model", "Scoring scripts and descriptions drafted from reference PDFs"):
        note(
            "On an instrument's page, a language model can write the scoring scripts and draft "
            "the description for the Measures paragraph from the instrument's reference PDF. The "
            "project names the provider and model; the key or the server stays on this computer."
        )
        env = KEY_ENV.get(provider)
        if env:
            note(
                "A cloud provider reads its key from an environment variable that you set "
                "yourself, for example by typing this in a terminal and restarting labcatalog:"
            )
            command(f"setx {env} your-key")
            found = os.environ.get(env)
            key = ui.label()
            show_status(
                key, f"{env} is {'set' if found else 'not set'}.", "ok" if found else "warn"
            )
            return
        note(
            "A local model runs on an OpenAI-compatible server such as Ollama or LM Studio; "
            "give its address, for example http://localhost:11434/v1."
        )
        with ui.row().classes("w-full items-start gap-2 mt-1"):
            url = (
                ui.input("Server address", value=preferences.load().get(preferences.LLM_URL, ""))
                .props("outlined dense")
                .classes("w-72")
            )
            ui.button("Save", on_click=lambda: save())
        status = ui.label()
        status.visible = False

        def save() -> None:
            preferences.save({preferences.LLM_URL: (url.value or "").strip()})
            show_status(status, "Saved.", "ok")
            on_model()
