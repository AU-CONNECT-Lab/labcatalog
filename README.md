# labcatalog

labcatalog builds a browsable catalog of a lab's study data. You describe your instruments, studies and data files once, and it gives you a desktop window where you can browse every instrument and variable across waves, see where the data disagree with the metadata, run the analyses most papers need, and copy the results as tables and text into a manuscript.

It works with questionnaires and with features from other modalities (EEG, fMRI, eye tracking, physiological measures and others), and it does not assume any particular lab, study design or discipline.

![The Overview page of the example project](docs/images/app/overview.png)

## How it works

![Your data, prepared by your own scripts, described in plain files and checked, then used to browse, analyze and write up](docs/images/workflow.png)

Each step has its own page in the window, so the whole loop runs without a terminal. The files stay plain YAML and CSV in your project folder, readable and versioned like any other code:

![The files labcatalog reads from your project folder and the files it writes there](docs/images/file-flow.png)

| In your project folder | What it holds | Step |
| --- | --- | --- |
| `raw/` | exports as they come off the platform or device | 1 Your data |
| `scripts/` | your cleaning and extraction scripts | 2 Prepare |
| `data/` | cleaned data files, one per dataset | 2 Prepare |
| `labcatalog.yaml` | settings, studies and waves, one entry per data file | 3 Describe |
| `instruments/` | one YAML file per instrument | 3 Describe |
| `studies/` | one YAML file per study: which instruments each dataset has | 3 Describe |
| `maps/` | one CSV per data file: which column is which item | 3 Describe |
| `references/` | `references.bib` and the instruments' PDFs | 3 Describe |
| `accepted_warnings.yaml` | warnings you have looked at and marked as fine | 4 Check |
| `outputs/` | tables, figures, scripts and data you saved | 5 Use |
| `freezes/` | records of which data a result used | 5 Use |
| `database/` | every dataset and its statistics in one DuckDB file | 5 Use |

## A look around

**Instruments**: items, options and scores of each instrument, with reliability, item analysis and factor structure in every wave.

![An instrument's page](docs/images/app/instrument.png)

**Analysis**: correlations, regressions, group comparisons and multilevel models on the sample you pick, in R or Python, with the code to rerun them.

![The Analysis page](docs/images/app/analysis.png)

**Methods**: the Participants and Measures paragraphs and APA tables for a wave, ready to paste.

![The Methods page](docs/images/app/methods.png)

**Problems**: every place the data and the metadata disagree, each with a plain explanation and a way to fix it.

![The Problems page](docs/images/app/problems.png)

## Install

labcatalog needs Python 3.11 or newer. Install it with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install "git+https://github.com/AU-CONNECT-Lab/labcatalog"
```

or with `pip install "git+https://github.com/AU-CONNECT-Lab/labcatalog"` in an environment of your choice. Then start it with `labcatalog gui`. The first time, it opens a fictional example project to look around in; **Open** in the header opens your own project folder.

## Documentation

The handbook, with a tour of the example, a page for each part of the window and how-to guides, is at <https://au-connect-lab.github.io/labcatalog/>. It is built from [docs/](docs/) with Jupyter Book: `pip install -e ".[docs]"`, then `jupyter-book start` in `docs/`.

## License

Apache-2.0. See [LICENSE](LICENSE).
