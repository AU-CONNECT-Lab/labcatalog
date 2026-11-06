# Export Variables and Data

An export collects the variables, data and statistics of chosen instruments into one folder, with a codebook in Word that describes them, ready to hand to a student or a collaborator or to open in other software.

## Export

1. On the **Instruments** page, tick the instruments you want and press **Export**. The dialog has three steps.
2. **Instruments**: the ticked instruments. Add or remove any here.
3. **Datasets**: every dataset that gives one of these instruments, laid out by wave and reporter. The datasets the page's filters show start ticked. Tick a wave or a reporter to take all of its datasets; hover over a dataset to see which of the instruments it has. When one of the instruments describes a study's participant roster (see [IDs, Groups and Missing Codes](../concepts/ids-groups-missing.md)), a box for that roster follows, ticked.
4. **Format**: the list of what will be exported, what goes into the folder (**Data**, **Statistics** and **Codebook**, all ticked to start with) and how the data are laid out:
   - **One file per dataset**: a CSV file for each dataset, as in the data.
   - **One table, a row per person (ID)**: one wide table across datasets, with the study and the ID as its first two columns, since IDs belong to their study. Each other column starts with its dataset's name.
   - **One table, a row per group**: the same, with one row per group, such as a family. Shown when the project has a group.

   Untick **Data** for a codebook and variable list without any data, such as for someone deciding which variables to ask for.
5. Press **Export**, then **Open folder**.

## What is in the folder

The export writes a new folder in `outputs/`:

| File | Content |
|---|---|
| `variables.csv` | Every item and score in each dataset: its study, wave, reporter, column, instrument, wording, type, options, allowed range and missing codes. |
| `<dataset>.csv` or `data_by_<id or group>.csv` | The data: the ID, group and date columns, the chosen items as they are in the data, and the scores labcatalog computes. |
| `roster_<study>.csv` | A ticked participant roster: its ID, group and role columns and the columns its instrument describes, in a file of its own whatever the layout. |
| `score_statistics.csv` | Each score's n, mean, SD, range and α in each dataset, and ω when the window has fitted the factor models (empty otherwise). |
| `item_statistics.csv` | The same for each item. |
| `codebook.docx` | A Word document for people to read and add to (see below). |
| `manifest.json` | The data files and checksums the export came from. |

Open answers (`text` items) are listed in `variables.csv` but never exported, since they can identify people. In a wide table, a person or group that appears more than once in one file cannot be placed in a single row; the export leaves those rows out and says how many.

## The codebook

`codebook.docx` describes what the export holds, so someone can use the data without opening labcatalog. It is written from the catalog each time; edit your copy freely, but change the instruments themselves in labcatalog and export again, as nothing flows back.

- **Front**: the project, each study's description and how to cite it, the missing codes, and where each person's group comes from.

- **Datasets**: one row per dataset with its wave, reporter, the dates its data were collected, its rows and people, its ID, respondent and date columns, its instruments and the prepare step that writes its file; then a row for each participant roster.

- **One section per instrument**: its description, construct, instructions, references and license, the datasets that give it, its response options, its items with their wording, and its scores with their items and how missing items are handled. Where the datasets differ (an item dropped or not mapped, an item reworded or given other options, reversed items already reversed in the data) a table says how. With **Statistics** ticked, each score's n, mean, SD and α in each dataset follow, and ω when the window has fitted the factor models.

- **Variables**: every column of the data files, by dataset, with its instrument and item or score, named as in the exported files.
