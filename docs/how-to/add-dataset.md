# Add a Wave or Dataset

Every new data file is a new dataset: a new wave of a study you already have, a new reporter, or a new modality.

## Add a wave

Add the wave to its study in `labcatalog.yaml`:

```yaml
studies:
  my_study:
    waves:
      1: {start: 2025-01-15, end: 2025-09-30}
      2: {start: 2026-01-15}
```

## Repeat a dataset from the window

For a file that repeats one you already have, such as the same questionnaire in the next wave, press **Add a dataset** on the Datasets page. The window copies the file in, runs its cleaning step, matches its columns to the catalogued items, and shows the changes to `labcatalog.yaml`, the column map and the study file before writing them. A new wave is added to the study without dates, to fill in afterwards. See [Datasets](../app/datasets.md#add-a-dataset). For a new reporter or modality, a folder dataset, or a dataset made by a more involved prepare step, follow the steps below.

## Add a CSV dataset

Put the cleaned file where the project can reach it, usually `data/`, and add an entry under `datasets`:

```yaml
datasets:
  - {name: parent_w2, modality: questionnaire, study: my_study, wave: 2, reporter: parent, source: csv, path: data/parent_w2.csv}
```

The file needs one row per person and a column with the participant ID (`id`, or the name given in `id_column`). Save files from Excel as CSV UTF-8. [Studies, Waves and Datasets](../concepts/studies-waves-datasets.md) lists the optional keys, such as `date_column` and `snapshot_date`.

If the modality or the reporter is new, add it to `vocab.modalities` or `vocab.reporters` too.

## Add a folder dataset

For data that are files rather than a table, such as scans in a BIDS folder, a folder dataset counts each person's files:

```yaml
  - {name: fmri_w2, modality: fmri, study: my_study, wave: 2, reporter: child, source: folder, path: /data/bids, files: "sub-{id}/ses-2/func/*_bold.nii.gz"}
```

Its data are the ID and a `files` column with the number of matching files. Map `files` to a `number` item of an instrument (for example "Resting-state runs") to see who has data in each wave. When a pipeline later extracts features, add them as a CSV dataset.

## Map its columns

A new dataset needs a column map and an administration for each instrument in it.

- If the file holds instruments that are already in the project, a codebook import is still the quickest way: the Import page matches items by their wording and reuses the instruments, and only writes the map. See [Add an Instrument](add-instrument.md).
- For a later wave with the same column names apart from a wave suffix, you can also copy the previous wave's map, rename it to `maps/<new dataset>.csv` and change the column names.

Then add the new dataset to each administration in the study file:

```yaml
administrations:
  - {instrument: parent_stress, datasets: [parent_w1, parent_w2], target: self}
```

Run `labcatalog check`, or press **Refresh** in the window, and look at the Problems page.
