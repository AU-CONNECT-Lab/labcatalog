import os
from collections.abc import Awaitable, Callable

from nicegui import run, ui

from labcatalog.charts import style
from labcatalog.exceptions import LabCatalogError
from labcatalog.gui import common, datalad, preferences, theme
from labcatalog.gui.common import note, section
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
) -> None:
    section("R")
    note(
        "Factor models (CFA) and ω run in R with lavaan and semTools, and the Analysis page "
        "uses R first, with psych and effectsize, and lme4, lmerTest and performance for the "
        "multilevel model; without R they use Python, except invariance across waves, which "
        "needs R. Install R and "
        f"the packages yourself ({install_command(ALL_PACKAGES)}), then give the path to "
        f"Rscript, which is in R's bin folder, for example {RSCRIPT_EXAMPLE}."
    )
    path = (
        ui.input("Rscript", value=preferences.load().get(preferences.RSCRIPT, ""))
        .props("outlined dense clearable")
        .classes("w-full mt-2")
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

    datalad.datalad_section(on_datalad)
    models_section(on_model)

    section("Appearance")
    ui.toggle(
        theme.APPEARANCES,
        value=preferences.load().get(preferences.APPEARANCE, theme.DEFAULT_APPEARANCE),
        on_change=lambda e: on_appearance(e.value),
    ).props("no-caps").classes("mt-2")
    ui.select(
        {name: p.label for name, p in style.PALETTES.items()},
        value=style.palette,
        label="Chart colors",
        on_change=lambda e: on_palette(e.value),
    ).props("outlined dense").classes("w-56 mt-2")

    section("Tables")
    note(
        "The Copy button under each table on the Analysis page copies it as a three-line table, "
        "as rich text for Word or Google Docs or as LaTeX (booktabs). Saving to outputs always "
        "writes each table as .csv, .docx and .tex."
    )
    ui.toggle(
        {preferences.RICH: "Word or Google Docs", preferences.LATEX: "LaTeX"},
        value=preferences.load().get(preferences.TABLE_FORMAT, preferences.RICH),
        on_change=lambda e: preferences.save({preferences.TABLE_FORMAT: e.value}),
    ).props("no-caps").classes("mt-2")
    ui.select(
        {places: str(places) for places in range(1, 5)},
        value=common.decimals,
        label="Decimal places in tables (p values keep three)",
        on_change=lambda e: on_decimals(e.value),
    ).props("outlined dense").classes("w-72 mt-2")


def models_section(on_model: Callable[[], None]) -> None:
    section("Language model")
    note(
        "On an instrument's page, a language model can write the scoring scripts and draft the "
        "description for the Measures paragraph from the instrument's reference PDF. A cloud provider reads its key from an environment variable "
        "that you set yourself, for example by running setx ANTHROPIC_API_KEY your-key in a "
        "terminal and restarting labcatalog. A local model runs on an OpenAI-compatible server "
        "such as Ollama or LM Studio; give its address, for example http://localhost:11434/v1."
    )
    saved = preferences.load()
    with ui.row().classes("items-start gap-4 mt-2"):
        provider = ui.select(
            PROVIDERS,
            value=saved.get(preferences.LLM_PROVIDER, preferences.DEFAULT_LLM_PROVIDER),
            label="Provider",
        ).classes("w-72")
        model = ui.input("Model", value=saved.get(preferences.LLM_MODEL, "")).classes("w-72")
        url = ui.input("Server address", value=saved.get(preferences.LLM_URL, "")).classes("w-80")
    url.bind_visibility_from(provider, "value", value="local")
    key = ui.label().classes("lc-note")
    status = ui.label().classes("lc-note")

    def show_key() -> None:
        env = KEY_ENV.get(provider.value)
        key.set_text(f"{env} is {'set' if os.environ.get(env) else 'not set'}." if env else "")

    def save() -> None:
        preferences.save(
            {
                preferences.LLM_PROVIDER: provider.value,
                preferences.LLM_MODEL: (model.value or "").strip(),
                preferences.LLM_URL: (url.value or "").strip(),
            }
        )
        status.set_text("Saved.")
        on_model()

    provider.on_value_change(lambda _: show_key())
    show_key()
    ui.button("Save", on_click=save).classes("mt-2")
