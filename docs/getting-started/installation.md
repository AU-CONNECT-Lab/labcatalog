# Installation

labcatalog is a Python package with a desktop window. It needs Python 3.11 or newer. R and a language model are optional.

## Requirements

- Windows, macOS or Linux.
- Python 3.11 or newer.
- Optional: R, for factor models and to run the analyses in R instead of Python. See [Set Up R and Language Models](../how-to/r-and-models.md).
- Optional: DataLad, if your data are in DataLad datasets. See [Using labcatalog with DataLad](../how-to/datalad.md).

## Install with uv

[uv](https://docs.astral.sh/uv/) installs labcatalog into an environment of its own, so it never conflicts with your other Python packages:

```bash
uv tool install "git+https://github.com/AU-CONNECT-Lab/labcatalog"
```

To update it later:

```bash
uv tool upgrade labcatalog
```

## Install with pip

In a virtual environment of your choice:

```bash
pip install "git+https://github.com/AU-CONNECT-Lab/labcatalog"
```

## Optional: language models

labcatalog can ask a language model to draft an instrument from its PDF, write scoring scripts, or find items by their wording. These features need the `ai` extra:

```bash
uv tool install "labcatalog[ai] @ git+https://github.com/AU-CONNECT-Lab/labcatalog"
```

Everything else works without it. What the model writes is always a draft for you to check; see [Add an Instrument](../how-to/add-instrument.md).

## Check the installation

Open the window:

```bash
labcatalog
```

The first time, the window opens the example project; after that, it opens the project that was open when it last closed. The next page tours the example.
