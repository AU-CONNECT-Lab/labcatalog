# Query the Data in a Database

labcatalog can write the whole project into one DuckDB file: every dataset as a table, what each column means, and the statistics of each item and score. Open it in R, Python or a database browser such as DBeaver to join datasets and waves with SQL. The files stay the source: the database is rebuilt from them whenever you ask, and labcatalog never reads it back.

## Build it

On the **Datasets** page, press **Build database**. It writes `database/labcatalog.duckdb` in the project folder, built from scratch each time, from the data as the window has them loaded; press **Refresh** first if the files changed since. If a build fails, the previous database stays.

The database holds row-level data, so keep it out of git: add `database/` to the project's `.gitignore`.

## What it holds

| Table | One row per |
|---|---|
| `data."<dataset>"` | Person in that dataset, with the ID, group and date columns, every item column and every score labcatalog computes, named as in [exports](export-data.md). |
| `variables` | Item or score column of every dataset: its instrument, item or score, text, type, response options, reverse scoring, missing codes and, for a score, its items and missing rule. |
| `datasets` | Dataset: study, wave, reporter, modality, path, rows and participants. |
| `score_statistics` | Score in each dataset: n, mean, SD, median, range and α. |
| `item_statistics` | Item in each dataset: n, missing codes, mean, SD, range and the count of each option. |
| `files` | Data file read: its checksum and rows. |
| `build` | The build: when, the labcatalog version and the git commit of the metadata. |

A column whose values are all numbers is stored as numbers, with missing codes kept as the values they are (so `-99` is still `-99`; `variables` says what it means). Blank cells are `NULL`. The dataset's date column is a date. Open answers are left out, as in exports, since they can identify people.

## Open it

In R:

```r
library(duckdb)
con <- dbConnect(duckdb(), "database/labcatalog.duckdb", read_only = TRUE)
dbGetQuery(con, 'SELECT * FROM data."child_w1"')
```

In Python:

```python
import duckdb
con = duckdb.connect("database/labcatalog.duckdb", read_only=True)
con.sql('SELECT * FROM data."child_w1"').df()
```

## With a freeze

A [freeze](datalad.md) writes its own copy beside its record, `freezes/<date>_<name>.duckdb`, which does not change afterwards: cite that version. Like the database, it holds row-level data; keep `freezes/*.duckdb` out of a public repository, or let DataLad store it in the annex.
