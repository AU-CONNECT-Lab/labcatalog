# Studies

The Studies page shows and edits each study under `studies` in `labcatalog.yaml`: its label, description and reference, its waves and its milestones. The studies are listed on the left; click one to open it. See [Studies, Waves and Datasets](../concepts/studies-waves-datasets.md).

## A study

The top of a study shows its ID, which cannot be changed here, and:

- **Label**: how the study reads in the window.
- **Description**: a sentence or two on what the study is.
- **Reference**: the key in `references.bib` of how to cite the study's data, chosen from the keys in the file. The "How to cite" line below it shows the citation.

## Waves

One row per wave, with its **Start** and **End** dates written as `2026-03-01`. **Status** says whether the wave is planned (it starts after today), collecting (it has started and has no end date, or ends after today) or finished, and **Datasets** how many datasets belong to it. Double-click a cell to edit it. **Add wave** adds a row with the next number, and **Delete ticked** removes the rows you ticked. A wave that still holds datasets cannot be removed: saving stops and lists the datasets that name it.

## Milestones

Dates shown on the [Overview](overview.md) timeline, such as an interim report or a data freeze, each with a **Name** and a **Date**. **Add milestone** and **Delete ticked** work as for waves.

## Datasets

The study's datasets, as on the [Datasets](datasets.md) page. Click a row to open the dataset there. A new study has none yet: add its first dataset to the Datasets table of `labcatalog.yaml` on the [Edit](edit.md) page. Later waves can then come in through **Add a dataset** on the Datasets page.

## Saving

**Save** and **Discard** are on once something has changed. **Save** checks the whole project with the change in place and writes nothing if it would cause a new error; the problems are listed under the study's fields. Otherwise only the lines you changed are written, comments stay where they were, and the catalog reloads. **Discard** throws your changes away. Opening another study with unsaved changes asks first.

## New study

**New study** asks for an ID (lower-case letters, digits and underscores, starting with a letter) and a label. It adds the study under `studies` in `labcatalog.yaml` and creates its study file, `studies/<id>.yaml`, with only the `study` key. Fill in its waves here, then add its datasets.
