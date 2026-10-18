# Settings

The Settings page, opened with the gear at the top right of the window, has three parts. **This project** holds the choices shared with the lab: they are saved in the project's `labcatalog.yaml`, so everyone who opens the project starts from them. **This computer** holds the paths to R, Mplus, Python and DataLad and what a language model needs on this computer. **Only for you** holds how the window looks and what the copy buttons copy.

When one labcatalog serves several people ([`labcatalog serve`](../how-to/work-as-a-team.md)), **This computer** only shows what the person running it set, **Only for you** is kept for each browser, and the example is not offered.

![The Settings page](../images/app/settings.png)

## Shared with the lab

Saved in `labcatalog.yaml` with **Save**, after which the project reloads:

- **Decimal places**: 1 to 4, 2 by default, for the numbers in tables and paragraphs. *p* values always keep three.
- **Two groups**: Welch's or Student's *t* test.
- **Correlations**: Pearson's *r* or Spearman's ρ.
- **Factor models**: WLSMV (items as ordered categories), ML or MLR (items as continuous).
- **Missing values**, **Imputed data sets** and **Imputation seed**: whether the Analysis page's sections use everyone with values or multiple imputation, and how it is drawn.
- **Language model provider** and **Model**: Anthropic, OpenAI, Gemini, or a local OpenAI-compatible server, and the model's name.
- **What a cleaning script's model sees of a raw file**: each column's different values (the default), or the raw file's first 20 rows.

These are where each page starts. A switch on a section of the Analysis page, or on the factor model panels, tries another choice for what that section shows, without changing the project; the table notes say which was used. See [Statistics](../statistics/index.md).

## R

The path to `Rscript`. **Save and check** runs R once and reports its version and any missing packages, with the command to install them. See [Set Up R and Language Models](../how-to/r-and-models.md).

**Analyses in R at once** (2 unless changed) caps how many analyses run in R together, from every window of this labcatalog; the rest wait their turn, so several windows or people cannot fill the computer's memory. **R processes for bootstrap resamples** is how many R processes one mediation's resamples are split over.

## Python

The Python that runs the Python scripts of the Analysis page's Custom tab, which needs pandas, numpy, scipy, statsmodels, semopy and matplotlib. **Save and check** reports its version and any missing packages, with the command to install them. Left empty, labcatalog installed with pip uses its own Python; the Windows program has none, so a Python must be set here to run Python scripts.

## DataLad

The path to `datalad`. **Save and check** reports the versions of DataLad and git-annex. See [Using labcatalog with DataLad](../how-to/datalad.md).

## Language model

What the project's language model needs on this computer. A cloud provider's API key is read from an environment variable that each person sets, and is never stored, in the project or anywhere else; the page gives the command and says whether it is set. For a local server, its address, with **Save**.

## Appearance

**Light** (the default), **Dark**, or **Same as the system**. Charts follow the window's colors. **Chart colors** chooses the color palette of every chart.

## Tables

**Word or Google Docs** or **LaTeX**: what the copy buttons copy. See [Copy Tables into a Manuscript](../how-to/copy-tables.md).

## Where the settings are kept

The project's in `labcatalog.yaml` (see [The Project File](../reference/project-file.md)). The rest in a file named `gui.json`: `%APPDATA%\labcatalog` on Windows, `~/Library/Application Support/labcatalog` on macOS, and `~/.config/labcatalog` on Linux.

## Example project

The example the window opens the first time, and with **Open example**, is a copy kept with these settings, so changes made while trying it out stay there. **Reset the example** puts it back as installed, after asking.
