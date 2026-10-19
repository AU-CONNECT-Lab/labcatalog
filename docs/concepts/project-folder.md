# The Project Folder

A project is one folder with `labcatalog.yaml` at its top. labcatalog reads the metadata from a fixed set of subfolders. The data can be inside the project folder or anywhere else: every path in the metadata is relative to the project folder unless it is absolute, and paths may start with `~` or contain environment variables, which helps when the data are on a shared drive.

```text
my_project/
    labcatalog.yaml     settings, studies and waves, one entry per data file
    instruments/        one YAML file per instrument
    studies/            one YAML file per study
    maps/               one CSV file per data file
    data/               cleaned data files (any location works)
    raw/                raw exports (optional)
    scripts/            your cleaning and extraction scripts (optional)
    references/         references.bib and the instruments' PDFs (optional)
    schemas/            JSON Schema files for your editor
    codebook/           codebook imports in progress
    drafts/             instruments drafted by a language model, not yet in the catalog
    outputs/            tables, figures and exports you saved
    freezes/            records of the data at a point in time
```

## labcatalog.yaml

The project file. It names the project; lists the allowed words for modalities, reporters and targets; gives the codes that mean "no answer" and the format of participant IDs; describes each study and its waves; and has one entry per data file. It also holds the prepare steps and the statistics settings. [labcatalog.yaml](../reference/project-file.md) lists every key.

## instruments/

One file per instrument, named after its ID, for example `instruments/example_mood.yaml`. An instrument is described once and can be used in any number of datasets, studies and waves. See [Instruments](instruments.md).

## studies/

One file per study, for example `studies/mock_study.yaml`. It says which instruments were given in which datasets, records how the study changed an item, and describes how each modality's data were collected. See [Column Maps and Overrides](variable-maps.md).

## maps/

One CSV file per dataset, named after the dataset, for example `maps/parent_w1.csv`; datasets with the same columns can share one. It links each column of the data file to an item of an instrument. See [Column Maps and Overrides](variable-maps.md).

## data/ and raw/

The data files the catalog reads. labcatalog never changes them. Many labs keep the raw exports from their survey platform in `raw/` and make a cleaned copy in `data/` with a script; [Register Prepare Steps](../how-to/prepare-steps.md) shows how labcatalog can run those scripts for you.

## scripts/

Your own scripts that turn raw exports and pipeline outputs into the files in `data/`. labcatalog runs them only when you ask, from the **Add data** step of the Set up page or the Scripts page.

## references/

`references.bib`, exported from a reference manager such as Zotero or pasted in with **Add references** (see [The Editor](../app/edit.md#editor-references)), and the PDFs of the instruments' references. This folder is often on a shared drive; `references.root` in `labcatalog.yaml` points to it.

## outputs/

Everything you save or export from the window goes into a new subfolder here, named with the date and time. Each subfolder also holds `manifest.json`, which records which data files, at which checksums, the saved numbers came from.

## drafts/, codebook/ and freezes/

`drafts/` holds instruments drafted by a language model until you have checked them and moved them into `instruments/`. `codebook/` holds the three CSV files of a codebook import while you fill them in. `freezes/` holds a record of the data each time you freeze them; see [Using labcatalog with DataLad](../how-to/datalad.md).

## Settings that are not in the project

The path to R, the language model, chart colors and the table format for copying belong to your computer, not to the project. They are set on the **Settings** page and are not shared with others who open the project. Settings that change the numbers, such as the correlation coefficient or the t test, are in `labcatalog.yaml`, so everyone who opens the project gets the same results.
