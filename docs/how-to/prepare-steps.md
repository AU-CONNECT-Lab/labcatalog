# Register Prepare Steps

The files in `data/` are usually made by your own scripts: one cleans each survey export, another turns a pipeline's per-person outputs into one row per person. When you register these scripts as prepare steps, labcatalog shows which data files are out of date and can run the scripts in order, so the data can always be rebuilt from the raw files.

labcatalog does not care what the scripts do or what language they are in. It runs a command and watches the files you name.

## Write a step

Steps go under `prepare` in `labcatalog.yaml`, in the order they should run:

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

## Run the steps

The **Prepare data** step of the Set up page lists every step with its status and the dates of its files. Press **Run** on one step, **Run outdated** to run only the steps that are not up to date, or **Run all** to run every step in order; a step that fails stops the rest. **Stop** ends the running step, and **Log** shows what the command printed. Press **Refresh** afterwards to read the new data.

On the command line, this runs every step in order and stops at the first failure:

```bash
labcatalog prepare
```

`labcatalog check` also warns about outdated steps (`prepare_outdated`).

## Run in R

A step can call `Rscript` directly. When the window runs a step, it puts the folder of the Rscript set on the Settings page first on the PATH, so `Rscript` is found even when R is not on your PATH. The command line uses the `Rscript` on your PATH.

## Record the steps with DataLad

If the project is a DataLad dataset, `prepare_with: datalad` runs each step through `datalad run`, which records the command, its inputs and its outputs in the dataset's history. See [Using labcatalog with DataLad](datalad.md).
