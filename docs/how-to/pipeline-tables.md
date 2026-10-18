# Bring In a Pipeline's Tables

Many processing pipelines for fNIRS, EEG and MRI end with a table: one row per recording, one column per measure, and a JSON sidecar that explains each column. `labcatalog derivatives` turns such a table into the files labcatalog reads: an instrument for the measures, a column map and a data file for each wave. You then add a few lines to `labcatalog.yaml` and the study file once, and register the command as a prepare step so it runs again whenever the pipeline does.

## What the table needs

- A tab-separated file (`.tsv`).
- A way to tell whose row it is: a `bids_name` column such as `sub-001_ses-01_task-nback_nirs`, or a `participant_id` column (and `session_id` when there are sessions). The IDs in the data file are written as `sub-001`, so they match the other modalities' IDs only if those use the same form.
- Optionally, a sidecar with the same name and `.json`, giving each column a `LongName`, a `Description` and `Units`. These become the item's short name and text. A column with `Levels` (`{"0": "no", "1": "yes"}`) becomes a choice item with those options, and columns with the same levels share one response set. Sidecars higher up follow the BIDS inheritance principle: up to the folder with `dataset_description.json`, a `.json` with the table's suffix whose entities are all in the table's name describes it too (`task-rest_qc.json` for `sub-01/ses-01/sub-01_ses-01_task-rest_qc.tsv`), and the one nearer the table, or naming more of its entities, wins. A `dataset_description.json` above the table names the pipeline and its version in the instrument's description.

Only columns whose values are all numbers (or `n/a`), or whose sidecar gives their `Levels`, become items. The command lists the columns it left out.

## Run it

In the **Describe columns** step of the Set up page, **From a pipeline's table** does the same with a form. On the command line:

```bash
labcatalog derivatives derivatives/nirspipe/desc-subjects_qc.tsv --name fnirs_qc --label "fNIRS quality" --study cmx7 --modality fnirs --reporter self --split task --columns "raw_*"
```

| Option | Meaning |
|---|---|
| `--name` | Starts the IDs of the instruments and datasets it writes: `fnirs_qc_w1` and so on. |
| `--study`, `--modality`, `--reporter` | Where the datasets belong, as in `labcatalog.yaml`. |
| `--split` | An entity whose values become separate instruments, such as `task`: one instrument per task, with columns like `nback_raw_sci_mean`. Repeat it for more entities. Without it, each person may have only one row per session. |
| `--columns` | Only the columns matching this pattern; repeat for more. All numeric columns by default. |
| `--wave` | The wave of every row, for a table without sessions. With sessions, `ses-01` is wave `1`. |
| `--label` | The instruments' name; `--name` when left out. |

It writes `instruments/<name>_<value>.yaml`, and `data/<name>_w<wave>.csv` and `maps/<name>_w<wave>.csv` for each wave. The first time, it also prints the lines to add: the study's new waves and the datasets in `labcatalog.yaml`, and the administrations in the study file. Add them, then run `labcatalog check`.

## Run it again

Running the command again rewrites the data files and the column maps, and the instruments' items follow the table's columns. Everything else you change in the instrument files stays: the name, the description, references, and your wording of an item. Register the command as a prepare step, after the step that runs the pipeline:

```yaml
prepare:
  - name: fnirs_qc
    run: labcatalog derivatives derivatives/nirspipe/desc-subjects_qc.tsv --name fnirs_qc --study cmx7 --modality fnirs --reporter self --split task --columns "raw_*"
    inputs: [derivatives/nirspipe/desc-subjects_qc.tsv]
    outputs: [data/fnirs_qc_w1.csv, data/fnirs_qc_w2.csv, data/fnirs_qc_w3.csv]
```

## Measures your own script computes

A pipeline may leave measures you compute yourself, such as the mean response in a region. Have your script write them the same way, a `.tsv` with `participant_id` and `session_id` columns and a `.json` sidecar, and bring them in with the same command. See [Register Prepare Steps](prepare-steps.md).
