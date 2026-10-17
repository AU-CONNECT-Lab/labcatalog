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
| `name` | The dataset's ID. Its column map is `maps/<name>.csv`. |
| `modality` | What kind of data it holds; one of `vocab.modalities`. |
| `study`, `wave` | The study and wave it belongs to. |
| `reporter` | Who provided the data; one of `vocab.reporters`. |
| `source` | `csv` for a table, `folder` for a folder of files. |
| `path` | The file, or for a folder dataset the folder. |
| `id_column` | The column with participant IDs, when it is not `defaults.id_column`. |
| `group_column` | A column with each person's group, when the group is not read from the ID. |
| `date_column` | A column with the date each row was collected, for the "collected by month" chart. |
| `wave_column` | In a file that holds several waves, the column naming each row's wave. |
| `snapshot_date` | The date the file was exported, shown as "data as of". |
| `missing_codes` | Missing codes for this file only, in place of the project's. |

### One file with several waves

When one file holds every wave, one row per person per wave, give each wave its own dataset that points at the same file, and name the column that says which wave a row belongs to:

```yaml
datasets:
  - {name: parent_w1, modality: questionnaire, study: mock_study, wave: 1, reporter: parent, source: csv, path: data/parent_long.csv, wave_column: wave}
  - {name: parent_w2, modality: questionnaire, study: mock_study, wave: 2, reporter: parent, source: csv, path: data/parent_long.csv, wave_column: wave}
```

Each dataset reads only the rows whose `wave` column matches its own `wave`, written the same way (`1` matches `1`, not `01` or `T1`). Everything else treats it as a file of its own: each dataset has its own column map in `maps/`, where the wave column is listed like the ID column, with no instrument. If the file has rows for a wave that no dataset reads, `labcatalog check` warns with `wave_unclaimed`. Problems point to the row's line in the shared file.

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
