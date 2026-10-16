# Column Maps

One CSV file per dataset in `maps/`, named after the dataset: `maps/<dataset>.csv`. The file is UTF-8; from Excel, save it as "CSV UTF-8".

The header must contain three columns:

| Column | Meaning |
|---|---|
| `column` | A column of the data file, exactly as it is written there. |
| `instrument` | The instrument's ID, or empty for a column that is not an item. |
| `item` | The item's ID, or `score:` and a score's ID for a column with a score your lab computed. Empty when `instrument` is empty. |

```text
column,instrument,item
pid,,
visit_date,,
ems_1_w1,example_mood,ems_1
ems_total_w1,example_mood,score:ems_total
```

Rules:

- `instrument` and `item` are filled together or left empty together.
- Every column of the data file should have a row; the ones without are reported as `column_unmapped`.
- Every column named in the map must exist in the data file (`column_missing`).
- Every item of an instrument given in the dataset should have a column, unless an override drops it (`unmapped_item`).
- A column appears once, and an item is mapped to one column.
- Empty rows are ignored.
