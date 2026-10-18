# Column Maps and Overrides

Instruments describe questions; data files have columns. Three things connect them: the column map of each dataset, the administrations in the study file, and the overrides that record how a study changed an item.

## Column maps

Each dataset has a column map, `maps/<dataset>.csv`, with three columns:

```text
column,instrument,item
pid,,
visit_date,,
ems_1_w2,example_mood,ems_1
ems_2_w2,example_mood,ems_2
ems_3_w2,example_mood,ems_3
```

Each row names a column of the data file and the instrument and item it holds. Columns that are not items, such as the ID or a date, have an empty instrument and item. `column_unmapped` warns about columns of the data file the map does not list, and `unmapped_item` about items of an administered instrument that have no column.

A column that holds a score your lab already computed is mapped to `score:` and the score's ID, for example `score:ems_total`; labcatalog then compares it with its own computation.

You rarely write a column map by hand. A codebook import writes it (see [Add an Instrument](../how-to/add-instrument.md)), and the **Edit files** step of the Set up page can change it. Excel can open and save it; choose "CSV UTF-8" when saving.

## Administrations

The study file says which instruments were given in which datasets:

```yaml
study: mock_study
administrations:
  - {instrument: example_parent_stress, datasets: [parent_w1, parent_w2, parent_w3], target: self}
  - {instrument: example_child_sleep, datasets: [parent_w1, parent_w2, parent_w3], target: child}
  - {instrument: example_mood, datasets: [child_w1, child_w2, child_w3], target: self}
```

An administration can also set:

| Key | Meaning |
|---|---|
| `target` | Who the instrument is about; one of `vocab.targets`. |
| `abbreviation` | The name this study used for the instrument, when it differs. |
| `reversed_in_data` | `true` when reverse-keyed items are already reversed in the data. |
| `overrides` | Changes to single items (below). |

## Overrides

Studies change instruments: an item is reworded for children, a response scale is shortened, an item is left out of one wave. An override records such a change without copying the instrument:

```yaml
administrations:
  - instrument: example_mood
    datasets: [child_w1, child_w2, child_w3]
    overrides:
      - {item: ems_9, text: I had fun with other kids.}
      - {item: ems_5, dataset: child_w1, dropped: true}
```

| Key | Meaning |
|---|---|
| `item` | The item it changes. |
| `dataset` | Only this dataset; without it, every dataset of the administration. |
| `text` | The wording used. |
| `response_set` | Another response set of the instrument. |
| `dropped` | `true` when the item was not asked. |

When several overrides apply to the same item, the later ones win.

## Methods

The study file also describes how each modality's data were collected and processed, in a paragraph or two that the Methods page and the Datasets page show:

```yaml
methods:
  questionnaire: |
    Parents filled in their questionnaires online in the week after each visit.
  eeg: |
    Resting EEG was recorded for five minutes with eyes closed from a 32-channel cap.
```
