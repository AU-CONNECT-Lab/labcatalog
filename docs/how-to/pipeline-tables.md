# Bring In a Pipeline's Tables

Many processing pipelines for fNIRS, EEG and MRI end with a table: one row per recording, one column per measure, and a JSON sidecar that explains each column. **From a pipeline's table** in the **Add data** step of the Set up page turns such a table into the files labcatalog reads: an instrument for the measures, a column map and a data file for each wave. You then add a few lines to `labcatalog.yaml` and the study file once.

## What the table needs

- A tab-separated file (`.tsv`).
- A way to tell whose row it is: a `bids_name` column such as `sub-001_ses-01_task-nback_nirs`, or a `participant_id` column (and `session_id` when there are sessions). The IDs in the data file are written as `sub-001`, so they match the other modalities' IDs only if those use the same form.
- Optionally, a sidecar with the same name and `.json`, giving each column a `LongName`, a `Description` and `Units`. These become the item's short name and text. A column with `Levels` (`{"0": "no", "1": "yes"}`) becomes a choice item with those options, and columns with the same levels share one response set. Sidecars higher up follow the BIDS inheritance principle: up to the folder with `dataset_description.json`, a `.json` with the table's suffix whose entities are all in the table's name describes it too (`task-rest_qc.json` for `sub-01/ses-01/sub-01_ses-01_task-rest_qc.tsv`), and the one nearer the table, or naming more of its entities, wins. A `dataset_description.json` above the table names the pipeline and its version in the instrument's description.

Only columns whose values are all numbers (or `n/a`), or whose sidecar gives their `Levels`, become items. The columns it left out are listed when the files are written.

## Write the files

In the **Add data** step of the Set up page, **From a pipeline's table** brings the table in. Press **Choose table** to pick the `.tsv`, fill in the form, and press **Write the files**.

| Field | Meaning |
|---|---|
| **Name** | Starts the IDs of the instruments and datasets it writes: `fnirs_qc_w1` and so on. |
| **Study**, **Modality**, **Reporter** | Where the datasets belong, as in `labcatalog.yaml`. |
| **Split by** | Entities whose values become separate instruments, such as `task`: one instrument per task, with columns like `nback_raw_sci_mean`. Without it, each person may have only one row per session. |
| **Columns** | Only the columns matching these patterns, such as `raw_*`. Every column of numbers, or with `Levels`, when left empty. |
| **Wave** | The wave of every row, for a table without sessions. With sessions, `ses-01` is wave `1`. |
| **Instrument name** | The instruments' name; the **Name** when left empty. |

Several values in one field are separated by spaces or commas. It writes `instruments/<name>_<value>.yaml`, and `data/<name>_w<wave>.csv` and `maps/<name>_w<wave>.csv` for each wave, and lists the columns it left out. The first time, it also shows the lines to add: the study's new waves and the datasets in `labcatalog.yaml`, and the administrations in the study file. Add them, then press **Refresh**.

## When the pipeline runs again

**Keep as a prepare step**, on by default, adds a prepare step named `table_` and the Name, such as `table_qc`, that takes the table in again with the same fields. It reads the table and its sidecars and writes the data files, so when the pipeline writes the table again the step shows as outdated, and **Run outdated** in the Add data step takes it in, as **Write the files** would. labcatalog runs this step itself rather than by a command, so with `prepare_with: datalad` it is not recorded by `datalad run`; save the data afterwards. Without the step, choose the table again in **From a pipeline's table** with the same fields and press **Write the files**. Either way, the data files and the column maps are rewritten, and the instruments' items follow the table's columns. Everything else you change in the instrument files stays: the name, the description, references, and your wording of an item.

## Measures your own script computes

A pipeline may leave measures you compute yourself, such as the mean response in a region. Have your script write them as a pipeline would, a `.tsv` with `participant_id` and `session_id` columns and a `.json` sidecar, and bring them in the same way. See [Register Prepare Steps](prepare-steps.md).
