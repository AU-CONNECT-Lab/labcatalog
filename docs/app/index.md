# Using the App

Open the window with `labcatalog gui`, or with `labcatalog gui -p <folder>` to open a project directly. The pages are listed on the left; this section describes them one by one.

## Opening a project

The window opens the project that was open when it last closed, or the example project the first time. **Open project** in the header chooses a project folder, the one with `labcatalog.yaml` in it, and **Open example** opens the example. The header then shows the project's name (hover over it for the folder) and the date the data are as of, from the datasets' `snapshot_date`.

## Refreshing after a change

labcatalog reads the project when it opens it. After you change a file, in the window or in an editor, press **Refresh** to read it again. Your filters and choices stay as they were.

The factor models take longer than the rest, so they run in the background after the catalog appears; their tables fill in when they are done.

## When a project has problems

The **Problems** tab shows how many problems the project has, in red when any is an error.

- If the metadata have errors, the window opens the Problems page, and the catalog pages say "The project files have errors. Fix them, then press Refresh." Fix the files on the Edit page or in an editor.
- If the data cannot be read, for example because a data file does not exist yet, the catalog pages show the error. The Prepare and Edit pages still work, so you can run the steps that make the data.

## The pages

| Page | What it is for |
|---|---|
| [Overview](overview.md) | The project at a glance: waves, collection, scores. |
| [Instruments](instruments.md) | Browse, search and export instruments; each instrument's items, scores, reliability and factor structure. |
| [Studies](studies.md) | Each study's label, reference, waves, milestones and methods text; new, renamed and deleted studies. |
| [Datasets](datasets.md) | Each data file: who is in it, completeness, missing values; freezes. |
| [Analysis](analysis.md) | Correlations, regression, group comparisons and multilevel models. |
| [Methods](methods.md) | Draft text and tables for a methods section. |
| [Prepare](prepare.md) | Run the scripts that make the data. |
| [Import](import.md) | Create instruments and a column map from a codebook. |
| [Edit](edit.md) | Edit the project's files as text or tables. |
| [Problems](problems.md) | Every mismatch between metadata and data. |
| [Settings](settings.md) | R, DataLad, the language model, charts and tables. |
