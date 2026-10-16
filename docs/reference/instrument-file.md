# Instrument Files

One file per instrument in `instruments/`, named after its ID. `id` and `name` are required. See [Instruments](../concepts/instruments.md) for how the parts fit together.

```yaml
# yaml-language-server: $schema=../schemas/instrument.schema.json
id: example_mood
name: Example Mood Scale
```

## Top level

| Key | Type | Default | Meaning |
|---|---|---|---|
| `id` | text | | The instrument's ID. Required. |
| `name` | text | | Its full name. Required. |
| `abbreviation` | text | | Its usual abbreviation. |
| `kind` | text | `questionnaire` | `questionnaire`, `demographics`, or a modality such as `eeg`. |
| `construct_name` | text | | What it measures. |
| `description` | text | | A sentence or two for the Measures paragraph. |
| `measures` | text | | This instrument's own Measures template. |
| `instructions` | text | | The instructions respondents saw. |
| `response_sets` | list | | Named lists of response options. |
| `default_response_set` | text | | The response set of items that do not name one. |
| `items` | list | | The items. |
| `scores` | list | | The scores. |
| `references` | list | | References, each with a `key` in `references.bib` and an optional `pdf` path inside the references folder. |
| `license` | text | | How the instrument may be used. |
| `custom` | mapping | | Values of custom fields that apply to instruments. |

## response_sets

| Key | Meaning |
|---|---|
| `id` | The response set's ID. |
| `options` | A list of options, each with the `value` stored in the data (number or text) and the `label` respondents saw. |

## items

| Key | Type | Default | Meaning |
|---|---|---|---|
| `id` | text | | The item's ID, unique within the instrument. Required. |
| `label` | text | the text | A short name for tables and text, such as "Child age". |
| `text` | text | | The wording. Required. |
| `type` | `choice`, `number` or `text` | `choice` | Answered with an option, an amount, or an open answer. |
| `response_set` | text | | Its response set, when not the default. |
| `min`, `max` | number | | The allowed range of a `number` item. |
| `reverse` | true or false | `false` | Reverse-scored. |

## scores

| Key | Type | Default | Meaning |
|---|---|---|---|
| `id` | text | | The score's ID. Required. |
| `label` | text | | Its name, such as Total. Required. |
| `method` | `sum` or `mean` | | How the items are combined. Required. |
| `items` | list of text | | The item IDs. Required. |
| `missing_rule` | `complete`, `prorate` or `zero` | `complete` | What to do with missing items. |
| `min_valid` | number | | The fewest answered items that still give a score. |
| `custom` | mapping | | Values of custom fields that apply to scores. |
