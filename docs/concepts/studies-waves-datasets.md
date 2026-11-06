# Studies, Waves and Datasets

A **study** collects data in one or more **waves**. Each data file is a **dataset**, and every dataset belongs to exactly one study, one wave, one modality and one reporter.

## Studies and waves

Studies are listed in `labcatalog.yaml`:

```yaml
studies:
  mock_study:
    label: Mock Family Study
    description: A fictional three-wave study in which parents and their children answer questionnaires once a year.
    reference: mockstudy2026
    waves:
      1: {start: 2024-03-01, end: 2024-10-31}
      2: {start: 2025-03-01, end: 2025-10-31}
      3: {start: 2026-03-01}
    milestones:
      - {name: Interim report, date: 2026-12-15}
```

The key (`mock_study`) is the study's ID, and `label` is how it reads in the window. `reference` is the key in `references.bib` of how to cite the study's data. Waves are named by their key, usually a number; a wave with no `end` is still collecting. `milestones` are dates shown on the Overview timeline.

## Datasets

Each data file has one entry under `datasets`:

```yaml
datasets:
  - {name: parent_w1, modality: questionnaire, study: mock_study, wave: 1, reporter: parent, source: csv, path: data/parent_w1.csv, date_column: visit_date}
```

| Key | Meaning |
|---|---|
| `name` | The dataset's ID. Its column map is `maps/<name>.csv`, unless `map` names another. |
| `modality` | What kind of data it holds; one of `vocab.modalities`. |
| `study`, `wave` | The study and wave it belongs to. |
| `reporter` | Who provided the data; one of `vocab.reporters`. |
| `source` | `csv` for a table, `folder` for a folder of files. |
| `path` | The file, or for a folder dataset the folder. |
| `id_column` | The column with participant IDs, when it is not `defaults.id_column`. |
| `respondent_column` | The column with the ID of whoever filled in each row, when the row's ID is the person it is about: a parent's answers on each of their children, one row per child. Participant counts and retention count the respondents; linking still uses `id_column`. |
| `date_column` | A column with the date each row was collected, for the "collected by month" chart. |
| `wave_column` | In a file that holds several waves, the column naming each row's wave. |
| `wave_value` | How that column writes this dataset's wave, when not as `wave`: `T1` for wave `1`. |
| `occasion` | Which time this is when one questionnaire is given several times in a wave, such as `{time: before, interaction: peer}`. |
| `snapshot_date` | The date the file was exported, shown as "data as of". |
| `missing_codes` | Missing codes for this file only, in place of the project's. |

### One file with several waves

When one file holds every wave, one row per person per wave, give each wave its own dataset that points at the same file, and name the column that says which wave a row belongs to:

```yaml
datasets:
  - {name: parent_w1, modality: questionnaire, study: mock_study, wave: 1, reporter: parent, source: csv, path: data/parent_long.csv, wave_column: wave}
  - {name: parent_w2, modality: questionnaire, study: mock_study, wave: 2, reporter: parent, source: csv, path: data/parent_long.csv, wave_column: wave}
```

Each dataset reads only the rows whose `wave` column matches its own `wave`, written the same way (`1` matches `1`, not `01` or `T1`). When the column writes the waves another way, give each dataset its `wave_value`, such as `wave_value: T1` on wave `1`; the dataset then reads the rows with `T1`, and the rest of labcatalog still calls it wave 1. Everything else treats it as a file of its own: each dataset has its own column map in `maps/`, where the wave column is listed like the ID column, with no instrument. When the waves have the same columns, they can share one map (see [One map for several datasets](variable-maps.md#one-map-for-several-datasets)). If the file has rows for a wave that no dataset reads, `labcatalog check` warns with `wave_unclaimed`. Problems point to the row's line in the shared file. When the file gains a wave, **Repeat a dataset** on the [Datasets](../app/datasets.md#add-a-dataset) page adds the next dataset for it, and the Datasets table in the editor in the **Codebook** step of the Set up page has **Wave column** and **Wave in the file** columns.

### One questionnaire given several times in a wave

When a questionnaire is given more than once in the same wave, such as before and after a task, or once about a parent and once about a friend, each time is a dataset of its own: the same study, wave and reporter, the same instrument in its administration, and a column map that links only that time's columns. In a survey export with one row per person, the datasets all point at the same file:

```yaml
datasets:
  - {name: panas_before, modality: questionnaire, study: mock_study, wave: 1, reporter: child, source: csv, path: data/visit_w1.csv, occasion: {time: before}}
  - {name: panas_after, modality: questionnaire, study: mock_study, wave: 1, reporter: child, source: csv, path: data/visit_w1.csv, occasion: {time: after}}
```

`maps/panas_before.csv` links `panas_pre_1` and so on to the items, `maps/panas_after.csv` links `panas_post_1` and so on to the same items, and each time gets its own scores, such as `panas.pa@panas_before` and `panas.pa@panas_after`. A column that another dataset of the same file links counts as described, so `labcatalog check` warns with `column_unmapped` only about columns that no dataset of the file lists. One map cannot link two columns to the same item, which is why each time needs its own dataset.

`occasion` says which time each dataset is, with names and values of your own: `{time: before}`, or `{time: before, interaction: peer}` when the times also differ in another way. Lists of variables name such datasets by wave and occasion, as "Wave 1 · before", and the [multilevel model](../app/analysis.md#multilevel-model) can take each name as a factor of the same people's scores. In the Datasets table of the editor, the **Occasion** column holds them as `time: before, interaction: peer`.

## Modalities

`vocab.modalities` lists the kinds of data in the project, such as `questionnaire`, `eeg` or `fmri`. The words are yours to choose. `vocab.modality_labels` says how each one reads in tables and in the Methods text:

```yaml
vocab:
  modalities: [questionnaire, eeg, fmri]
  modality_labels: {questionnaire: questionnaires, eeg: EEG, fmri: fMRI}
```

For modalities other than questionnaires, a dataset usually holds features that a pipeline extracted, one row per person: band power from EEG, connectivity from fMRI, cortisol from saliva. They are described as an instrument whose items are numbers, so they can be browsed, checked and analyzed like questionnaire scores.

## Reporters and targets

The **reporter** of a dataset is who provided its data: a parent filling in a questionnaire, a child answering on a tablet, or the child who was scanned. The **target** of an administration, set in the study file, is who the instrument is about: a parent may report on themselves (`self`) or on their child (`child`). Both lists are yours to define in `vocab.reporters` and `vocab.targets`.

## CSV and folder datasets

A `csv` dataset is a table with one row per person. A `folder` dataset is a folder of files, such as a BIDS folder of scans. labcatalog does not open the files; it counts, for each person, how many files match a pattern:

```yaml
  - {name: fmri_w1, modality: fmri, study: my_study, wave: 1, reporter: child, source: folder, path: bids, files: "sub-{id}/ses-1/func/*_bold.nii.gz"}
```

`{id}` marks the part of each path that holds the participant ID, which must be written the same way as the IDs in your other datasets. `*` matches any part of a file name and `**` any number of folders. The dataset then has two columns: the ID and `files`, the number of files found, which you map to an item like any other column. This shows who has data in each wave before any features are extracted.
