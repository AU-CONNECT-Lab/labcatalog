import os
from collections.abc import Awaitable, Callable

from nicegui import ui

from labcatalog.charts import style
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common, datalad, example, preferences, theme
from labcatalog.gui.common import command, computed, note, panel, path_input, show_status
from labcatalog.llm import KEY_ENV, PROVIDERS
from labcatalog.stats.rbridge import ALL_PACKAGES, install_command, r_status

RSCRIPT_EXAMPLE = r"C:\Program Files\R\R-4.5.2\bin\Rscript.exe"


def render(
    on_appearance: Callable[[str], Awaitable[None]],
    on_palette: Callable[[str], None],
    on_rscript: Callable[[], Awaitable[None]],
    on_model: Callable[[], None],
    on_datalad: Callable[[], Awaitable[None]],
    on_decimals: Callable[[int], None],
    on_reset_example: Callable[[], Awaitable[None]],
) -> None:
    with ui.row().classes("w-full no-wrap items-start gap-4"):
        with ui.column().classes("grow min-w-0 gap-4"):
            r_section(on_rscript)
            datalad.datalad_section(on_datalad)
            models_section(on_model)
        with ui.column().classes("w-96 shrink-0 gap-4"):
            looks_section(on_appearance, on_palette)
            tables_section(on_decimals)
            example_section(on_reset_example)


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


def looks_section(
    on_appearance: Callable[[str], Awaitable[None]], on_palette: Callable[[str], None]
) -> None:
    with panel("Appearance"):
        ui.toggle(
            theme.APPEARANCES,
            value=preferences.load().get(preferences.APPEARANCE, theme.DEFAULT_APPEARANCE),
            on_change=lambda e: on_appearance(e.value),
        ).props("no-caps")
        ui.select(
            {name: p.label for name, p in style.PALETTES.items()},
            value=style.palette,
            label="Chart colors",
            on_change=lambda e: on_palette(e.value),
        ).props("outlined dense").classes("w-full mt-2")


def tables_section(on_decimals: Callable[[int], None]) -> None:
    with panel(
        "Tables",
        "The Copy button under each table on the Analysis page copies it as a three-line "
        "table, as rich text for Word or Google Docs or as LaTeX (booktabs). Saving to outputs "
        "always writes each table as .csv, .docx and .tex.",
    ):
        ui.toggle(
            {preferences.RICH: "Word or Google Docs", preferences.LATEX: "LaTeX"},
            value=preferences.load().get(preferences.TABLE_FORMAT, preferences.RICH),
            on_change=lambda e: preferences.save({preferences.TABLE_FORMAT: e.value}),
        ).props("no-caps")
        ui.select(
            {places: str(places) for places in range(1, 5)},
            value=common.decimals,
            label="Decimal places in tables (p values keep three)",
            on_change=lambda e: on_decimals(e.value),
        ).props("outlined dense").classes("w-full mt-2")


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
    with panel("Language model", "Scoring scripts and descriptions drafted from reference PDFs"):
        note(
            "On an instrument's page, a language model can write the scoring scripts and draft "
            "the description for the Measures paragraph from the instrument's reference PDF. A "
            "cloud provider reads its key from an environment variable that you set yourself, "
            "for example by typing this in a terminal and restarting labcatalog:"
        )
        command("setx ANTHROPIC_API_KEY your-key")
        note(
            "A local model runs on an OpenAI-compatible server such as Ollama or LM Studio; "
            "give its address, for example http://localhost:11434/v1."
        )
        saved = preferences.load()
        with ui.row().classes("w-full items-start gap-2 mt-1"):
            provider = (
                ui.select(
                    PROVIDERS,
                    value=saved.get(preferences.LLM_PROVIDER, preferences.DEFAULT_LLM_PROVIDER),
                    label="Provider",
                )
                .props("outlined dense")
                .classes("w-60")
            )
            model = (
                ui.input("Model", value=saved.get(preferences.LLM_MODEL, ""))
                .props("outlined dense")
                .classes("w-60")
            )
            url = (
                ui.input("Server address", value=saved.get(preferences.LLM_URL, ""))
                .props("outlined dense")
                .classes("w-72")
            )
            ui.button("Save", on_click=lambda: save())
        url.bind_visibility_from(provider, "value", value="local")
        key = ui.label()
        status = ui.label()
        status.visible = False

        def show_key() -> None:
            env = KEY_ENV.get(provider.value)
            key.visible = env is not None
            if env:
                found = os.environ.get(env)
                show_status(
                    key, f"{env} is {'set' if found else 'not set'}.", "ok" if found else "warn"
                )

        def save() -> None:
            preferences.save(
                {
                    preferences.LLM_PROVIDER: provider.value,
                    preferences.LLM_MODEL: (model.value or "").strip(),
                    preferences.LLM_URL: (url.value or "").strip(),
                }
            )
            show_status(status, "Saved.", "ok")
            on_model()

        provider.on_value_change(lambda _: show_key())
        show_key()
