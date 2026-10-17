# Export Variables and Data

An export collects the variables, data and statistics of chosen instruments into one folder, ready to hand to a student or a collaborator or to open in other software.

## In the window

1. On the **Instruments** page, tick the instruments you want and press **Export**. The dialog has three steps.
2. **Instruments**: the ticked instruments. Add or remove any here.
3. **Datasets**: every dataset that gives one of these instruments, laid out by wave and reporter. The datasets the page's filters show start ticked. Tick a wave or a reporter to take all of its datasets; hover over a dataset to see which of the instruments it has.
4. **Format**: the list of what will be exported, and how the data are laid out:
   - **One file per dataset**: a CSV file for each dataset, as in the data.
   - **One table, a row per person (ID)**: one wide table across datasets. Each column starts with its dataset's name.
   - **One table, a row per group**: the same, with one row per group, such as a family. Shown when the project has a group.
5. Press **Export**, then **Open folder**.

## On the command line

```bash
labcatalog export example_mood example_parent_stress
labcatalog export example_mood --dataset child_w1 --dataset child_w2 --by id
```

The arguments are instrument IDs. `--dataset` limits the export to some datasets (all of them by default), and `--by` chooses the layout: `dataset`, `id`, or the group's name.

## What is in the folder

The export writes a new folder in `outputs/`:

| File | Content |
|---|---|
| `variables.csv` | Every item and score in each dataset: its study, wave, reporter, column, instrument, wording, type, options, allowed range and missing codes. |
| `<dataset>.csv` or `data_by_<id or group>.csv` | The data: the ID, group and date columns, the chosen items as they are in the data, and the scores labcatalog computes. |
| `score_statistics.csv` | Each score's n, mean, SD, range and α in each dataset, and ω when the window has fitted the factor models (the command line leaves it empty). |
| `item_statistics.csv` | The same for each item. |
| `manifest.json` | The data files and checksums the export came from. |

Open answers (`text` items) are listed in `variables.csv` but never exported, since they can identify people. In a wide table, a person or group that appears more than once in one file cannot be placed in a single row; the export leaves those rows out and says how many.
