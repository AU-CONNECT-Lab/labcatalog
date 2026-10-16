# Fix Reported Problems

labcatalog checks a project in two passes. `labcatalog validate` reads only the metadata: the YAML files and the column maps. `labcatalog check` also reads the data and compares every value with what the metadata allow. The **Problems** page shows the result of both, and updates when you press **Refresh**.

## Read a problem

Each problem has a level, a code, a message and a location:

```text
data/parent_w1.csv: error [unexpected_value] eps_4_w1: 1 value(s) are neither response options nor missing codes: 7
labcatalog.yaml: error [not_in_vocab] datasets[3] (child_w1).reporter: 'kid' is not in vocab.reporters
maps/child_w2.csv:14: error [map_row] instrument and item must be filled together
```

- An **error** means labcatalog cannot trust the result: a value that is not allowed, an ID used twice, a key it does not know. Fix errors first.
- A **warning** points to something worth a look that may be fine: people who gave the same answer to every item, a column the map does not describe.

The location names the file, and where it can, the line or the entry: `datasets[3] (child_w1).reporter` is the `reporter` of the third dataset in `labcatalog.yaml`. On the Problems page, the location is a link that opens the file on the Edit page at that line.

The command line exits with status 1 when there are errors, so `labcatalog check` can stop a script or a CI job.

## Problems in the metadata

| Code | What it means | What to do |
|---|---|---|
| YAML errors, unknown keys | A file cannot be read, or a key is misspelled. | Fix the file at the line shown. Every key labcatalog does not know is an error, so typos never pass silently. |
| `not_in_vocab` | A modality, reporter or target is not in `vocab`. | Add the word to `vocab`, or fix its spelling. |
| `unknown_reference` | Something names an ID that does not exist: an instrument, item, response set, dataset or study. | Fix the ID, or add what it names. |
| `duplicate_id` | Two things share an ID. | Rename one. |
| `map_missing` | A dataset has administrations but no column map. | Create `maps/<dataset>.csv`, for example with a codebook import. |
| `unmapped_item` | An administered instrument has items with no column in the map. | Map them, or record them as dropped with an override. |
| `missing_code_collision` | A missing code is also a response option. | Change the missing code, or use dataset-specific `missing_codes`. |
| `reference_missing`, `bib_missing`, `pdf_missing` | A reference key is not in `references.bib`, or a file is not where it should be. | Export `references.bib` again, or fix `references.root` or the `pdf` path. |

## Problems in the data

| Code | What it means | What to do |
|---|---|---|
| `unexpected_value` | A value is neither a response option nor a missing code, or a number is outside `min` and `max`. | Fix the data in your cleaning script, or add the option or missing code if it is real. |
| `id_whitespace`, `id_missing`, `id_duplicate`, `id_pattern` | An ID has stray spaces, is empty, appears twice in one file, or does not match `ids.pattern`. | Fix the IDs in your cleaning script. |
| `column_missing` | The map names a column the data file does not have. | Fix the map, or the column name in the data. |
| `column_unmapped` | The data file has a column the map does not list. | Add it to the map, with an empty instrument and item if it is not an item. |
| `score_mismatch` | A score in the data differs from the score labcatalog computes. | Check the scoring rule: reversed items, `missing_rule`, `min_valid`. |
| `same_answer` | People gave the same answer to every item of a score. | Look at them; they may have answered without reading. |
| `possible_identifier` | A column's name suggests it holds names, emails, phone numbers, addresses or birth dates. | Remove it from the data the catalog reads. |
| `excluded_present` | Rows belong to someone on the exclusion list. | Remove them in your cleaning script. |
| `prepare_outdated`, `prepare_output_missing` | A prepare step's inputs are newer than its outputs, or an output does not exist. | Run the step on the Prepare page. |
| `not_downloaded` | A file in a DataLad dataset has no content on this computer. | Get it; see [Using labcatalog with DataLad](datalad.md). |

[Problem Codes](../reference/problem-codes.md) lists every code.

## Fix the data, not the catalog

labcatalog never changes your data files. When a problem is in the data, fix it where the data are made, usually in the cleaning script, and run that step again. The fix is then recorded in the script and survives the next export.
