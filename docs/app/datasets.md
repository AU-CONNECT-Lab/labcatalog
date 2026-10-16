# Datasets

The Datasets page shows each study and its data files: who is in each file, how complete their answers are, which values are missing and why, and the freezes made of the data.

## Studies

Each study has a card with its label, its description and, when the study has a `reference`, a "How to cite" line taken from `references.bib`. Below it, a table lists the study's datasets:

| Column | Meaning |
|---|---|
| Dataset, Wave, Reporter, Modality | From the dataset's entry in `labcatalog.yaml`. |
| Rows | Rows in the file. |
| IDs | Distinct participant IDs. |
| Collected | The first and last date in the `date_column`. |
| Data as of | The dataset's `snapshot_date`. |

Click a row to open the dataset.

## A dataset

The top of a dataset's page lists its study, wave, reporter and modality; its rows and IDs; with a group, the number of groups; how many people were also in the previous wave and how many are new; when it was collected; and the data file, which opens in its own application when clicked. **All datasets** goes back to the list.

Below that:

- **Methods**: how this modality's data were collected and processed, from `methods` in the study file.
- **Instruments**: each instrument in the file, with how many people answered all, some or none of its items. Open answers do not count. Click a row to open the instrument.
- **Missing values**: how many cells are blank, how many hold each missing code, and how many hold a value that is neither an answer nor a missing code.
- **Collected by month**: rows per month, when the dataset has a `date_column`.
- **Problems**: the problems found in this file and its column map. The file links open the Edit page at the line.
- **Label code**: R code (with haven) and Python code (for pyreadstat) that puts the item wording, response labels and missing codes on the data, for example to save it as an SPSS file.

## Freezes

A freeze records every data file the catalog reads, with its checksum, rows and participants, so you can say later which data a result used. Press **Freeze**, give the freeze a name such as `2026-06-submission`, and press **Freeze** in the dialog. The record goes to `freezes/`. If the data are in DataLad, the freeze also saves each dataset and tags it with the name, so that version can be opened again later; otherwise the record shows whether the data changed, but cannot bring back data that were overwritten.

The **Freezes** table lists every freeze, newest first. A freeze with a DataLad tag has an **Open** button, which opens a copy of the project as it was at that freeze. The header then says which freeze is shown and whether the data match its record, and **Back to the project** returns to the current project. See [Using labcatalog with DataLad](../how-to/datalad.md).

## Get missing content

When a project is a DataLad clone whose files have not been downloaded yet, it cannot load, and the page shows **Get missing content**. It downloads the metadata and then the data files the project reads, and reloads the project. It needs the path to `datalad` on the Settings page.
