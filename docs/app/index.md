# Using the App

Open the window with `labcatalog gui`, or with `labcatalog gui -p <folder>` to open a project directly. The pages are listed across the top, in groups: browsing the catalog (Overview, Instruments, Datasets), writing it up (Analysis, Methods), setting up the project (the numbered Set up steps: Codebook, Add data and Check IDs) and Problems. Two pages open from the top right instead: **Studies** beside the study picker opens the Studies page, and the gear opens Settings. This section describes the pages one by one.

## Opening a project

The window opens the project that was open when it last closed, or the example project the first time. **Open** in the header has two choices: **Open project** chooses a project folder, the one with `labcatalog.yaml` in it, and **Open example** opens the example. The header then shows the project's name (hover over it for the folder) and the date the data are as of, from the datasets' `snapshot_date`.

## One study or all

A picker at the top right chooses the study the pages show. **All studies** shows every study. With one study chosen, the Overview shows its datasets, waves, people, instruments and milestones; the Instruments and Datasets pages start with that study's filter set; the Analysis page offers its datasets; and the Studies and Methods pages open it. The Problems page starts with that study's filter set too. Set up and Settings always cover the whole project. The window remembers the choice for each project.

## Refreshing after a change

labcatalog reads the project when it opens it. After you change a file, in the window or in an editor, press **Refresh** to read it again. Your filters and choices stay as they were.

The factor models take longer than the rest, so they run in the background after the catalog appears; their tables fill in when they are done.

## When a project has problems

The **Problems** tab shows how many problems the project has, in red when any is an error.

- If the metadata have errors, the window opens the Problems page, and the catalog pages say "The project files have errors. Fix them, then press Refresh." Fix the files in the editor in the **Codebook** step of the Set up page or in an editor of your own.
- If the data cannot be read, for example because a data file does not exist yet, the catalog pages show the error. The Set up page still works, so you can run the prepare steps that make the data.

## The Set up page

Set up holds the work of building a project, in the order it is usually done. Its numbered steps sit in the row of pages at the top: **Codebook**, **Add data** and **Check IDs**. Click a step to open it; a step with something left to do shows how many things next to its name, and hovering over the number says what they are, such as "2 drafts" for instrument drafts to check, "3 to run" for prepare steps that are not up to date, "1 to link" for a data file with no column map, or "2 to check" for data files with ID problems. **Next** at the bottom of each step opens the one after it, and from the last step the [Review](review.md) of the data on the Datasets page. Switching steps keeps unsaved changes in the editor.

## The pages

| Page | What it is for |
|---|---|
| [Overview](overview.md) | The project at a glance: waves, collection, scores. |
| [Instruments](instruments.md) | Browse, search and export instruments; each instrument's items, scores, reliability and factor structure. |
| [Studies](studies.md) | Each study's label, reference, waves, milestones and procedure text; new, renamed and deleted studies. |
| [Datasets](datasets.md) | Each data file: who is in it, completeness, missing values; freezes. |
| [Analysis](analysis.md) | Correlations, regression, group comparisons and multilevel models. |
| [Methods](methods.md) | Draft text and tables for a methods section. |
| [Templates](templates.md) | The wording of the paragraphs labcatalog writes. |
| Set up | Steps in order: [Codebook](codebook.md) describes the instruments before there is data and holds [the editor](edit.md) of the project's files, [Add data](add-data.md) adds data files, their [prepare steps](prepare.md) and their column maps, [Check IDs](ids.md) checks and corrects each file's IDs; then [Review](review.md) on the Datasets page looks over each data file and its scores. |
| [Scripts](scripts.md) | Every script: the prepare steps that run it, its code, new scripts and steps. |
| [Problems](problems.md) | Every mismatch between metadata and data. |
| [Settings](settings.md) | R, DataLad, the language model, charts and tables. |
