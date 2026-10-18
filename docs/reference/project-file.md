# labcatalog.yaml

The project file, at the top of the project folder. Only `project.name` is required. Every key labcatalog does not know is reported as an error, so a misspelled key never passes silently.

```yaml
# yaml-language-server: $schema=schemas/labcatalog.schema.json
project:
  name: My Lab Catalog
```

## project

| Key | Type | Meaning |
|---|---|---|
| `name` | text | The project's name, shown in the window's header. Required. |

## vocab

The allowed words for each dataset's modality and reporter and each administration's target.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `modalities` | list of text | `[questionnaire]` | Kinds of data in the project. |
| `modality_labels` | mapping | none | How each modality reads in tables and prose, for example `{eeg: EEG}`. |
| `reporters` | list of text | none | Who provides data, for example `[parent, child]`. |
| `targets` | list of text | none | Who an instrument can be about, for example `[self, child]`. |

## missing_codes

A list of codes that mean "no answer", each with a `code` (number or text) and a `label`. Blank cells always count as missing. A dataset's own `missing_codes` replaces this list for that dataset.

```yaml
missing_codes:
  - {code: -99, label: refused}
  - {code: "", label: blank}
```

## defaults

| Key | Default | Meaning |
|---|---|---|
| `id_column` | `id` | The ID column of every dataset that does not set its own. |
| `date_format` | `%Y-%m-%d` | How dates in `date_column`s are written, in Python's `strftime` notation. |

## ids

| Key | Meaning |
|---|---|
| `pattern` | A regular expression every participant ID must match. |
| `group.name` | The name of the group, such as `family`. |
| `group.from_id` | A regular expression whose first group reads the group from an ID. Without it, each study's `roster` gives its people's groups. |

See [IDs, Groups and Missing Codes](../concepts/ids-groups-missing.md).

## studies

A mapping from each study's ID to:

| Key | Type | Meaning |
|---|---|---|
| `label` | text | How the study reads in the window. |
| `description` | text | A sentence or two about the study, shown on the Datasets page. |
| `reference` | text | The key in `references.bib` of how to cite the study's data. |
| `waves` | mapping | Each wave's key to its `start` and `end` dates (both optional). |
| `milestones` | list | Dates to show on the Overview timeline, each with a `name` and a `date`. |
| `roster` | mapping | The study's people, see below. |
| `id_pattern` | text | A regular expression the study's IDs must match, in place of `ids.pattern`, for a study that writes its IDs another way. |
| `exclusions` | text | A path to a CSV file with an `id` column listing people or groups of the study who must not be in the data. `labcatalog check` reports rows of the study's datasets that belong to them. |
| `custom` | mapping | Values of custom fields that apply to studies. |

IDs belong to their study: two studies may both have a `1001P`, and they are different people. So each study lists its own people and exclusions.

### roster

A CSV file listing everyone in the study once, one row per person. Optional.

| Key | Default | Meaning |
|---|---|---|
| `path` | | The file, relative to the project folder. |
| `id_column` | `defaults.id_column` | The column with each person's ID. |
| `group_column` | none | The column with each person's group, named by `ids.group.name`. Every dataset of the study takes its groups from here; a project gives `ids.group.from_id` or this, not both. A study without one links its files by ID. |
| `role_column` | none | The column with each person's role, one of `vocab.reporters`. Each dataset's respondents are then checked against its `reporter`. |
| `instrument` | none | A demographics instrument describing the roster's other columns, mapped to them in `maps/roster_<study>.csv`. The Analysis page offers its items for the people of every file of the study. |

## datasets

A list with one entry per data file.

| Key | Type | Meaning |
|---|---|---|
| `name` | text | The dataset's ID. Required. |
| `modality` | text | One of `vocab.modalities`. Required. |
| `study` | text | A study under `studies`. Required. |
| `wave` | text | One of the study's waves. Required. |
| `reporter` | text | One of `vocab.reporters`. Required. |
| `source` | `csv` or `folder` | A table, or a folder of files. Required. |
| `path` | path | The file, or the folder. |
| `files` | text | For a folder dataset: the files to count, with `{id}` where the path holds the ID. |
| `id_column` | text | The ID column, when it is not `defaults.id_column`. |
| `respondent_column` | text | The column with the ID of whoever filled in each row, when that is not the person the row is about. Counts of respondents use it. |
| `date_column` | text | A column with the date each row was collected. |
| `wave_column` | text | In a file that holds several waves, the column naming each row's wave; the dataset reads only the rows of its own `wave`. |
| `map` | text | The column map to read, as `maps/<map>.csv`, when the dataset shares one with others. Default: the dataset's name. |
| `wave_value` | text | How the wave column writes this dataset's wave, such as `T1`, when not the same as `wave`. |
| `snapshot_date` | date | The date the file was exported. |
| `missing_codes` | list | Missing codes for this dataset only. |
| `custom` | mapping | Values of custom fields that apply to datasets. |

## custom_fields

A list of fields your lab adds to instruments, scores, administrations or datasets.

| Key | Meaning |
|---|---|
| `name` | The key under `custom`. |
| `label` | How it reads in the window. |
| `applies_to` | `instrument`, `score`, `item`, `administration`, `dataset` or `study`. |
| `type` | `text`, `number`, `date`, `choice` or `tags`. |
| `choices` | The allowed values of a `choice` or `tags` field. |
| `vocabulary` | A vocabulary that comes with labcatalog, in place of `choices`: `rdoc`, the RDoC domains and their constructs. In the filters each term sits under its group, and a term also counts as its group. |

## browse

| Key | Default | Meaning |
|---|---|---|
| `facets` | `[study, wave, coverage, reporter, target, modality]`, then every `choice` and `tags` custom field, then `status` | The filters on the Instruments page, in order. Built in: `study`, `wave`, `coverage` (given in every wave or in fewer), `reporter`, `target`, `modality`, `status` (complete or what the catalog still lacks); any `choice` or `tags` custom field can be added. |

## references

| Key | Default | Meaning |
|---|---|---|
| `root` | the project folder | The folder holding `references.bib` and the reference PDFs. May start with `~` or contain environment variables. |

## stats

Settings that change the numbers, kept in the project so that everyone gets the same results. See [Statistics](../statistics/index.md).

| Key | Default | Values |
|---|---|---|
| `correlate_by` | `id` | `id`, the group's name, or `none`: how people in different datasets are matched. |
| `decimals` | `2` | 1 to 4: decimal places of the numbers in tables and paragraphs; *p* values keep three. |
| `missing` | `available` | `available` (each analysis on everyone with values) or `impute` (multiple imputation in R) for the Analysis page. |
| `imputations` | `20` | 2 to 500: the number of imputed data sets. |
| `seed` | `1` | The imputation's random seed. |
| `correlation` | `pearson` | `pearson` or `spearman`. |
| `t_test` | `welch` | `welch` or `student`. |
| `cfa_estimator` | `wlsmv` | The estimator factor models and invariance tests start from: `wlsmv` (items as ordered categories), `ml` or `mlr` (items as continuous; `mlr` is robust maximum likelihood). The pages can switch it for what they show. |
| `invariance_free` | none | Items whose parameters an invariance test lets differ, each as `{instrument, item, parameter, across}`: `parameter` is `loading`, `threshold` or `intercept`, and `across` is `waves`, `reporters`, or the grouping item as `instrument.item`. Written by **Save and rerun** on the invariance tables. |

## llm

The language model the lab uses, set on the Settings page. API keys are never kept here; each person sets theirs in an environment variable, and a local server's address is a setting of each computer. See [Set Up R and Language Models](../how-to/r-and-models.md).

| Key | Default | Values |
|---|---|---|
| `provider` | `anthropic` | `anthropic`, `openai`, `gemini` or `local` (an OpenAI-compatible server). |
| `model` | none | The model's name, as the provider gives it. |
| `raw_data` | `values` | What the model that drafts a cleaning script is given of the raw file: `values` (each column's different values) or `rows` (its first 20 lines). |

## prepare and prepare_with

`prepare` is a list of steps, each with a `name`, the command to `run`, its `inputs` and its `outputs`. `prepare_with: datalad` runs each step through `datalad run`. See [Register Prepare Steps](../how-to/prepare-steps.md).

## analyses

The analyses kept from the Custom tab of the Analysis page, each with a `name`, its `script` (in the `analyses` folder, `.R`, `.py` or `.inp`), the `datasets` and `variables` it reads, `every_dataset` (only people in every dataset, the default, or anyone in one) and the `request` it was drafted from. See [Analysis](../app/analysis.md).

## measures and participants

Templates of the Measures and Participants paragraphs on the Methods page. See [Write the Methods Section](../how-to/write-methods.md).

## schema_version

The version of this file's format, written by `labcatalog init`. Leave it as it is.
