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

## Use the Fix panel

On the Problems page, **Fix** at the end of a row opens a panel for that problem: what it means, who usually fixes it, the rows of the data it is about, and, where the fix is a change to the project files, the change itself. The panel checks a change before it saves it and refuses one that would leave a new error. [Problems](../app/problems.md#the-fix-panel) lists what it offers for each code. Work from the top: errors first, and one problem at a time, since fixing one can bring out another that it hid.

## Problems in the metadata

| Code | What it means | What to do |
|---|---|---|
| YAML errors, unknown keys | A file cannot be read, or a key is misspelled. | Fix the file at the line shown. Every key labcatalog does not know is an error, so typos never pass silently. |
| `not_in_vocab` | A modality, reporter or target is not in `vocab`. | In the Fix panel, pick the word it should be, or add the new word to `vocab`. |
| `unknown_reference` | Something names an ID that does not exist: an instrument, item, response set, dataset or study. | In the Fix panel, pick the ID it should be; or add what it names. |
| `duplicate_id` | Two things share an ID. | Rename one. For a column map that lists a row twice, the Fix panel takes one out. |
| `map_missing` | A dataset has administrations but no column map. | Create `maps/<dataset>.csv`, for example with a codebook import. |
| `unmapped_item` | An administered instrument has items with no column in the map. | In the Fix panel, pick each item's column, or record that the dataset did not ask it (a dropped override). |
| `missing_code_collision` | A missing code is also a response option. | If the value is an answer, take it out of the missing codes in the Fix panel (for one dataset or all). Otherwise change the response set. |
| `reference_missing`, `bib_missing`, `pdf_missing` | A reference key is not in `references.bib`, or a file is not where it should be. | Export `references.bib` again, or fix `references.root` or the `pdf` path. A mistyped key can be swapped in the Fix panel. |

## Problems in the data

| Code | What it means | What to do |
|---|---|---|
| `unexpected_value` | A value is neither a response option nor a missing code, or a number is outside `min` and `max`. | The Fix panel lists the rows. A typo is fixed in the cleaning script; a real value is added in the panel as a missing code or a new answer option. |
| `id_whitespace`, `id_missing`, `id_duplicate`, `id_pattern` | An ID has stray spaces, is empty, appears twice in one file, or does not match `ids.pattern`. | Fix the IDs in your cleaning script. |
| `id_not_in_roster` | An ID in the data is not in the roster: a typo, or a person nobody has added yet. | Fix the ID in your cleaning script, or add the person to the roster. |
| `column_missing` | The map names a column the data file does not have. | Pick the column's new name in the Fix panel, or take the row out of the map. |
| `column_unmapped` | The data file has a column the map does not list. | In the Fix panel, add it to the map as not an item, or as the item it holds. |
| `wave_unclaimed` | A file shared by several waves has rows for a wave no dataset reads. | Add a dataset for that wave (**Fix** has a button for each wave, which opens **Add a dataset** filled in), or make the wave in the data match the dataset's `wave`. |
| `score_mismatch` | A score in the data differs from the score labcatalog computes. | Check the scoring rule: reversed items, `missing_rule`, `min_valid`. |
| `same_answer` | People gave the same answer to every item of a score. | Look at them; they may have answered without reading. If their answers are real, record the warning as fine. |
| `possible_identifier` | A column's name suggests it holds names, emails, phone numbers, addresses or birth dates. | Remove it from the data the catalog reads. |
| `excluded_present` | Rows belong to someone on the exclusion list. | Remove them in your cleaning script. |
| `prepare_outdated`, `prepare_output_missing` | A prepare step's inputs are newer than its outputs, or an output does not exist. | Run the step from the Fix panel or on the Prepare page. |
| `not_downloaded` | A file in a DataLad dataset has no content on this computer. | Get it; see [Using labcatalog with DataLad](datalad.md). |

[Problem Codes](../reference/problem-codes.md) lists every code.

## A warning that is fine

A warning can be fine as it stands: three children who answered "never" to every mood item may simply have had a good fortnight. In the Fix panel, write why in **Why it is fine** and press **It is fine**. The warning leaves the Problems page and `labcatalog check`, which says how many accepted warnings it left out. The reason, who gave it and when are kept in `accepted_warnings.yaml` in the project folder; commit it with the rest of the project so others see the same list.

The warning comes back by itself when its message changes, for example when a new export adds a fourth child, so a decision about three children is not taken as one about four. To bring one back sooner, press **Show again** at the bottom of the Problems page. Errors cannot be accepted.

## Fix the data, not the catalog

labcatalog never changes your data files. When a problem is in the data, fix it where the data are made, usually in the cleaning script, and run that step again. The fix is then recorded in the script and survives the next export.
