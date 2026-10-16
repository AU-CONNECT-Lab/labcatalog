# Command Line

Every command that works on a project takes `--project` (`-p`), the project folder; the default is the current folder. Commands that check something exit with status 0 when there are no errors and 1 when there are, so they can be used in scripts.

## gui

```bash
labcatalog gui [-p PROJECT]
```

Open the labcatalog window, with the project if one is given.

## init

```bash
labcatalog init TARGET [--example | --no-example]
```

Create a new project in `TARGET`, which must be new or empty. By default it copies the fictional example project; `--no-example` writes an almost empty `labcatalog.yaml` with the folders `instruments/`, `studies/`, `maps/` and `data/`. Both write `schemas/`.

## validate

```bash
labcatalog validate [-p PROJECT]
```

Check the metadata (`labcatalog.yaml`, instrument and study files, column maps) without reading the data.

## check

```bash
labcatalog check [-p PROJECT]
```

Read the data and report every mismatch with the metadata, plus everything `validate` reports. See [Fix Reported Problems](../how-to/fix-problems.md).

## prepare

```bash
labcatalog prepare [-p PROJECT]
```

Run the prepare steps in `labcatalog.yaml` in order, stopping at the first failure. See [Register Prepare Steps](../how-to/prepare-steps.md).

## freeze

```bash
labcatalog freeze NAME [-p PROJECT]
```

Record the data as they are now under `NAME`, for example `2026-06-submission`. Datasets in DataLad are also saved and tagged. See [Using labcatalog with DataLad](../how-to/datalad.md).

## export

```bash
labcatalog export INSTRUMENT... [-d DATASET]... [--by dataset|id|GROUP] [-p PROJECT]
```

Write the variable list, the data and their statistics for the given instruments into a new folder in `outputs/`. `--dataset` (`-d`) limits the export to some datasets and can be repeated. `--by` chooses the layout: `dataset` (the default) for one file per dataset, `id` or the group's name for one wide table. See [Export Variables and Data](../how-to/export-data.md).

## codebook

Import the codebook of a dataset that has no column map yet. See [Add an Instrument](../how-to/add-instrument.md).

```bash
labcatalog codebook create DATASET [--redcap FILE | --qualtrics FILE | --spss FILE] [-p PROJECT]
```

Write `items.csv`, `instruments.csv` and `scores.csv` in `codebook/DATASET/`, listing every column of the data file. `--redcap` takes wording, options and item types from a REDCap data dictionary, `--qualtrics` from a Qualtrics survey file (`.qsf`), and `--spss` from the labels of an SPSS file (`.sav`).

```bash
labcatalog codebook prompt DATASET [-p PROJECT]
```

Print a prompt that asks a language model to fill in the three files from your codebook.

```bash
labcatalog codebook import DATASET [-p PROJECT]
```

Check the three files, then write the instrument files and `maps/DATASET.csv`, and print the lines to add to the study file.

## schema

```bash
labcatalog schema [-o FOLDER]
```

Write the JSON Schema files that let an editor check and complete the YAML files, by default into `schemas/` in the current folder. `labcatalog init` already does this; run it again after updating labcatalog.
