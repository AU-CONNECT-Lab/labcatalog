# Tour of the Example Project

labcatalog comes with a fictional project, the Mock Family Study: three yearly waves in which parents and their children answer questionnaires about stress, sleep, mood, worries and screen time, some families with two children, plus simulated EEG, fMRI, fNIRS, eye tracking, video coding, ECG and salivary cortisol data. It is small enough to read in full and has every part a real project has. It also contains a few deliberate data problems so that you can see how labcatalog reports them.

## Open the example

The window opens the example the first time you start it, and **Open example**, under **Open** in the header, opens it at any time. It is the window's own copy, so changes you make while trying things out never touch the installed package; **Reset the example** on the Settings page puts it back as installed.

To have the example in a folder of your own instead, copy it there and open it:

```bash
labcatalog init my_example
labcatalog gui -p my_example
```

`my_example` is then an ordinary project folder: change anything in it and press **Refresh** in the window to see the effect. To start over, delete the folder and run `labcatalog init` again.

## Look around the project folder

Open `my_example` in a file browser or editor. The parts you will meet in every project:

- `labcatalog.yaml`: the project's settings, its study and waves, and one entry per data file.
- `instruments/`: one YAML file per questionnaire or measure.
- `studies/mock_study.yaml`: which instruments were given in which data files, and how each modality's data were collected.
- `maps/`: one CSV file per data file, linking each column to an item.
- `data/`: the cleaned data files the catalog reads, and `participants.csv`, the roster that gives each person's family.
- `raw/`, `derivatives/` and `scripts/`: the raw exports, the pipeline outputs, and the scripts that turn them into `data/`.
- `references/`: the instruments' references and their PDFs.

[The Project Folder](../concepts/project-folder.md) describes each one.

## Browse instruments

The **Instruments** page lists the thirteen instruments. Use the filters at the top to narrow the list by wave, reporter or domain, then click **Example Mood Scale**. Its page shows the items and response options, the scores and how they are computed, their reliability in each wave, and how the scores change across waves. Under **One dataset**, pick `child_w1` to see item statistics, the R and Python code that computes the scores, and a draft Measures paragraph.

## Look at a dataset

The **Datasets** page shows the study and each of its twenty-one data files. Click `parent_w1` to see which instruments it holds, how many values are missing and why, when the data were collected, and the problems found in this file.

## Run an analysis

The **Analysis** page works on the datasets you pick under **Sample**. Pick `child_w1` and `parent_w1`: the correlation table shows how the children's mood scores relate to their parents' stress, linked through the family each ID belongs to. Below it are regression, group comparisons and a multilevel model. Each result has a **Copy** button for pasting into a manuscript and a **Code** section with the R and Python code that reproduces it.

## Read the Methods page

The **Methods** page drafts the parts of a methods section that the catalog already knows: how many people took part in each wave and modality, how the data were collected, a paragraph per instrument with its reliability, Table 1, and a comparison of those who stayed in the study with those who left.

## See the problems

The **Problems** page lists what `labcatalog check` found: values outside an item's options, an age outside its allowed range, an ID with a stray space, an ID used twice, people who gave the same answer to every item, and a column the column map does not describe. Each one links to where it can be fixed. [Fix Reported Problems](../how-to/fix-problems.md) explains them.

The **Prepare** page may also show some steps as outdated, because some of the example's scripts are newer than the files they made. Press **Run all** to rebuild the data from the raw files.
