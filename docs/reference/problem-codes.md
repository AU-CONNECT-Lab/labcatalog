# Problem Codes

Every problem has a level, a code, a message and, usually, a location. On the command line each one is a line:

```text
{location}: {level} [{code}] {message}
```

Errors mean a result cannot be trusted; warnings point to something worth a look. `labcatalog validate` and `labcatalog check` exit with status 1 when there is any error. [Fix Reported Problems](../how-to/fix-problems.md) explains how to work through them.

Loading comes first: if a file cannot be read (the codes in the first table), the other checks do not run until it is fixed. `check` reads the data only when the metadata have no errors.

## Reading the files

| Code | Level | Meaning |
|---|---|---|
| `yaml_syntax` | error | A YAML file cannot be read: a misplaced colon, a tab used for indentation, an unclosed quote or bracket, or a file not saved as UTF-8. The location gives the line when it can. |
| `extra_forbidden` | error | A key labcatalog does not know, usually a misspelling: "unknown key; check the spelling". |
| `missing` | error | A required key is missing: "required but missing". |
| other type codes | error | A value of the wrong type, such as `literal_error` (not one of the allowed words), `string_type`, `list_type`, `bool_parsing` or `date_from_datetime_parsing`. The message names the key and what was expected. |
| `map_encoding` | error | A column map is not UTF-8; in Excel, save it as "CSV UTF-8". |
| `map_header` | error | A column map's header lacks `column`, `instrument` or `item`. |
| `map_row` | error | A row of a column map has an instrument without an item or the other way round, or no column. |
| `bib_syntax` | error | An entry in `references.bib` cannot be read. |
| `not_downloaded` | error | A project file in a DataLad dataset has no content on this computer; get it with `datalad get`. |

## Metadata

| Code | Level | Meaning |
|---|---|---|
| `not_in_vocab` | error | A modality, reporter or target is not in `vocab`. |
| `unknown_reference` | error | Something names an ID that does not exist: a study, wave, dataset, instrument, item, score, response set or facet. Also a column map for a dataset that is not in `labcatalog.yaml`, or one that maps an instrument not given in that dataset. |
| `duplicate_id` | error | Two things share an ID: datasets, instruments, studies, items, scores, response sets, option values, prepare steps, reference keys, or rows of a column map. |
| `invalid_value` | error | A value that cannot work, for example a choice item without options, `min` above `max`, a score of text items, `min_valid` out of range, an invalid regular expression in `ids`, a dataset without `path`, or an unknown placeholder in a template. One case is a warning: `min_valid` with `missing_rule: complete`, where it has no effect. |
| `undeclared_custom_field` | error | A `custom` value for a field not declared in `custom_fields`, or declared for something else. |
| `missing_code_collision` | error | A response option has the same value as a missing code of a dataset where the instrument is given. |
| `map_missing` | error | A dataset has administrations but no column map. |
| `unmapped_item` | warning | Items of an instrument given in a dataset have no column in its map and are not dropped by an override. |
| `references_root_missing` | warning | The folder in `references.root` does not exist on this computer. |
| `bib_missing` | warning | Something cites a reference, but there is no `references.bib`. |
| `reference_missing` | warning | A reference key is not in `references.bib`. |
| `pdf_missing` | warning | A reference's PDF is not where its `pdf` says. |

## Data

| Code | Level | Meaning |
|---|---|---|
| `column_missing` | error | The column map names a column that is not in the data. |
| `column_unmapped` | warning | The data have columns that the column map does not list. |
| `wave_unclaimed` | warning | A file read by datasets with a `wave_column` has rows for a wave none of them reads. |
| `unexpected_value` | error | Values that are neither response options nor missing codes, or numbers outside `min` and `max`. |
| `id_missing` | error | Rows without an ID. |
| `id_whitespace` | error | IDs with leading or trailing spaces. |
| `id_pattern` | error | IDs that do not match `ids.pattern`. |
| `id_duplicate` | error | IDs that appear more than once in one file. |
| `group_missing` | warning | IDs from which no group can be read, or people the roster lists without a group. |
| `id_not_in_roster` | warning | IDs in the data that their study's roster does not list. |
| `roster_unused` | info | People in a study's roster who are in no dataset of the study. |
| `reporter_mismatch` | warning | Respondents whose role in the roster (the roster's `role_column`) is not the dataset's reporter. |
| `role_unknown` | warning | Roles in the roster that are not in `vocab.reporters`. |
| `id_map_invalid` | error or warning | A line of `id_map.csv` gives an ID two corrections or no new ID (error), or names a dataset the project does not have (warning). |
| `excluded_present` | error | Rows of people or groups on the exclusion list. |
| `possible_identifier` | warning | A column whose name or values suggest names, emails, phone numbers, addresses or birth dates. |
| `date_unparseable` | warning | Dates in the `date_column` that do not match `defaults.date_format`. |
| `same_answer` | warning | People who gave the same answer to every item of a score with five or more items. |
| `score_mismatch` | error | A score column in the data differs from the score labcatalog computes. |
| `score_coverage` | warning | Rows with a score in the data but not in labcatalog's computation, or the other way round. |
| `prepare_output_missing` | warning | A prepare step's output does not exist, or has not been downloaded. |
| `prepare_outdated` | warning | A prepare step's output is older than one of its inputs. |
| `git_annex_not_found` | warning | The project's files are in DataLad datasets, but git-annex cannot be found, so their versions are not recorded. |

## Codebook import

Problems found by **Check and import** in the **Describe columns** step of the Set up page, or by `labcatalog codebook import`, all have the code `codebook`. The location is the codebook file and line, such as `codebook/parent_w1/items.csv:12`, and the message says what is wrong in that row.

## Accepted warnings

`accepted_warnings.yaml` in the project folder lists the warnings someone looked at and recorded as fine, from the Fix panel on the Problems page. labcatalog writes it; it can also be edited by hand.

```yaml
accepted:
  - {code: same_answer, location: data/child_w1.csv, message: 'example_mood.ems_total@child_w1: 2 participant(s) gave the same answer to every item: 1021C, 1093C', reason: Checked the paper forms, by: Qiuyu, date: 2026-10-16}
```

| Key | Meaning |
|---|---|
| `code` | The problem's code. |
| `location` | The problem's location, left out when it has none. |
| `message` | The problem's message, word for word. |
| `reason` | Why the warning is fine. |
| `by` | Who accepted it: the name git records for them, or the computer's user name. |
| `date` | The day it was accepted. |

A warning is hidden only while its code, location and message all match an entry, so it shows again as soon as its message changes. Entries that match an error do nothing: errors are always reported. `labcatalog check` ends with the number of accepted warnings it did not print. A mistake in the file itself is reported like a mistake in any other project file.

## Errors that stop a command

Some problems stop a command before any check can run, and are printed as `Error: ...` instead: a data file or ID column that cannot be found, a data file that is not UTF-8, or a missing exclusion list. Fix the cause and run the command again.
