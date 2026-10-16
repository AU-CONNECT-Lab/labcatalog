# Your First Project

This page sets up a project for one data file and one questionnaire. Everything else (more waves, more instruments, other modalities) is more of the same.

## Create the folder

```bash
labcatalog init my_project --no-example
```

This creates `my_project/` with an almost empty `labcatalog.yaml`, the folders `instruments/`, `studies/`, `maps/` and `data/`, and `schemas/`. The comments in `labcatalog.yaml` show an example of every setting.

:::{tip}
The files in `schemas/` let an editor check your YAML and complete it as you type. In VS Code, install the YAML extension by Red Hat; every file labcatalog writes starts with a line that points the editor to the right schema.
:::

## Describe the study

Open `labcatalog.yaml`. Name the reporters who answer your questionnaires, and describe your study and its waves:

```yaml
vocab:
  modalities: [questionnaire]
  reporters: [parent]

studies:
  my_study:
    label: My Study
    waves:
      1: {start: 2026-01-15}
```

A wave without an end date is still collecting data.

## Add a dataset

Put your cleaned data file in `data/`, for example `data/parent_w1.csv`, with one row per person and an ID column. Then add an entry for it:

```yaml
datasets:
  - {name: parent_w1, modality: questionnaire, study: my_study, wave: 1, reporter: parent, source: csv, path: data/parent_w1.csv, id_column: record_id}
```

`id_column` is the name of the column that holds the participant IDs. If it is `id` in every file, you can leave it out. [Studies, Waves and Datasets](../concepts/studies-waves-datasets.md) explains each key.

## Add the instruments and map the columns

labcatalog now needs to know which questionnaire each column belongs to. The quickest way is to import a codebook: open the project in the window (`labcatalog gui -p my_project`), go to the **Import** page, pick `parent_w1`, and press **Create the three files**, or **Create from a REDCap data dictionary**, **Create from a Qualtrics survey file** or **Create from an SPSS file** if you have one. Fill in the three CSV files, press **Check and import**, and labcatalog writes the instrument files in `instruments/` and the column map `maps/parent_w1.csv`. [Add an Instrument](../how-to/add-instrument.md) describes this and the other ways.

## Say which instruments were given

The last step tells labcatalog which instruments were given in which data files. Create `studies/my_study.yaml`:

```yaml
study: my_study
administrations:
  - {instrument: my_questionnaire, datasets: [parent_w1]}
```

After an import, the Import page shows the exact lines to add.

## Check the project

```bash
labcatalog validate -p my_project
labcatalog check -p my_project
```

`validate` checks the YAML files and column maps without reading the data. `check` reads the data and reports every value that does not fit the metadata. In the window, press **Refresh** and open the **Problems** page to see the same list.
