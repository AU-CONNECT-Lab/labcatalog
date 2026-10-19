# Register Prepare Steps

The files in `data/` are usually made by your own scripts: one cleans each survey export, another turns a pipeline's per-person outputs into one row per person. When you register these scripts as prepare steps, labcatalog shows which data files are out of date and can run the scripts in order, so the data can always be rebuilt from the raw files.

labcatalog does not care what the scripts do or what language they are in. It runs a command and watches the files you name.

## Write a step

The [Scripts](../app/scripts.md) page writes a script and its step for you: **New script**, then **Add a step**. Steps go under `prepare` in `labcatalog.yaml`, in the order they should run:

```yaml
prepare:
  - name: clean_parent_w1
    run: python scripts/clean_export.py raw/parent_w1_export.csv data/parent_w1.csv
    inputs: [raw/parent_w1_export.csv, scripts/clean_export.py]
    outputs: [data/parent_w1.csv]
  - name: extract_eeg_w1
    run: Rscript scripts/extract_eeg.R derivatives/eeg/ses-1 data/eeg_w1.csv
    inputs: [derivatives/eeg/ses-1/qc.csv, scripts/extract_eeg.R]
    outputs: [data/eeg_w1.csv]
```

| Key | Meaning |
|---|---|
| `name` | The step's name. |
| `run` | The command. It runs in the project folder, so paths are relative to it. |
| `inputs` | The files the step reads. |
| `outputs` | The files the step writes: new files, never one of its inputs, and never a file another step writes. `labcatalog validate` reports a step that would overwrite what it reads, so the raw files stay as exported. |

A step is **outdated** when one of its inputs is newer than one of its outputs. List the script itself among the inputs, so that changing the script also marks the step outdated. A step is **missing output** when an output does not exist yet, and **missing input** when an input does not.

## From a database

Data kept in a SQLite or DuckDB file, such as a lab's visit tracker or a pipeline's run log, come in through a query. Write the query in a `.sql` file and let `labcatalog sql` write its result as a CSV file:

```yaml
prepare:
  - name: visits
    run: labcatalog sql tracker/visits.sqlite scripts/visits.sql data/visits.csv
    inputs: [tracker/visits.sqlite, scripts/visits.sql]
    outputs: [data/visits.csv]
```

The database is opened read only. The CSV file is then a dataset like any other, and changing the query or the database marks the step outdated. Databases on a server are not read directly; export from them with their own tools into a file first.

## Run the steps

The **Prepare steps** of the **Add data** step of the Set up page list every step with its status and the dates of its files. Press **Run** on one step, **Run outdated** to run only the steps that are not up to date, or **Run all** to run every step in order; a step that fails stops the rest. **Stop** ends the running step, and **Log** shows what the command printed. Press **Refresh** afterwards to read the new data.

On the command line, this runs every step in order and stops at the first failure:

```bash
labcatalog prepare
```

`labcatalog check` also warns about outdated steps (`prepare_outdated`).

## Draft a step with a language model

With a language model set on the Settings page (see [Set Up R and Language Models](r-and-models.md)), **Draft a cleaning step** at the bottom of the [Scripts](../app/scripts.md) page writes a first script for you. Choose the **Dataset**, the **Raw export** it comes from (a CSV file in the project folder) and **R** or **Python**, and press **Draft**.

The model is given the raw file's column names and, as the project sets on the Settings page, either each column's different values or its first 20 lines; and the dataset's columns from its column map, with each item's answer options, the missing codes and the ID pattern. It writes a script that takes the raw file and the clean file as arguments, as in `Rscript scripts/clean_parent_w1.R raw/parent_w1_export.csv data/parent_w1.csv`.

The script and the model's notes open in a window, and nothing is written until you press **Save**. Saving writes `scripts/clean_<dataset>.R` or `.py` and adds the step `clean_<dataset>` to `labcatalog.yaml`, with the raw file and the script as inputs and the dataset's file as output, in place of a step of the same name. Run the step and check the data as with any other.

When the Problems page reports a problem in a file a registered script writes, such as an ID with a space or a value outside the options, its panel has **Draft a fix to the script**: the model is given the script, the raw file, the dataset's columns and the problem with its rows, and returns the script changed. The window shows the change line by line, with what the model changed and what it left open, and **Save** writes the script. Then run the step again.

## Run in R

A step can call `Rscript` directly. When the window runs a step, it puts the folder of the Rscript set on the Settings page first on the PATH, so `Rscript` is found even when R is not on your PATH. The command line uses the `Rscript` on your PATH.

## Record the steps with DataLad

If the project is a DataLad dataset, `prepare_with: datalad` runs each step through `datalad run`, which records the command, its inputs and its outputs in the dataset's history. See [Using labcatalog with DataLad](datalad.md).
