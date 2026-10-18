# Instruments

An **instrument** is a questionnaire, a demographics form, or the set of features a pipeline extracts from one kind of recording. Each one is described once, in its own file in `instruments/`, and can be used in any number of datasets. This page uses the example's mood questionnaire, `instruments/example_mood.yaml`.

```yaml
id: example_mood
name: Example Mood Scale
abbreviation: EMS
construct_name: Mood and negative affect
description: It asks how often in the past two weeks the child felt sad, worried or tired, and how often they enjoyed things.
instructions: Think about the past two weeks. How often did you feel this way?
response_sets:
  - id: frequency
    options:
      - {value: 0, label: Never}
      - {value: 1, label: Sometimes}
      - {value: 2, label: Often}
      - {value: 3, label: Always}
default_response_set: frequency
items:
  - {id: ems_1, text: I felt happy., reverse: true}
  - {id: ems_2, text: I felt sad.}
  # ...
scores:
  - {id: ems_total, label: Total score, method: sum, items: [ems_1, ems_2, ems_3, ems_4, ems_5, ems_6, ems_7, ems_8, ems_9], missing_rule: prorate, min_valid: 7}
  - {id: ems_sadness, label: Sadness, method: sum, items: [ems_2, ems_6, ems_7]}
references:
  - {key: example2019, pdf: example_mood.pdf}
license: Free for research use (fictional)
```

`kind` says what sort of instrument it is: `questionnaire` (the default), `demographics`, or a modality such as `eeg`. `construct_name` and `description` feed the Measures paragraph on the Methods page. A description is one or two sentences that a person has written or checked.

## Items

Every item has an `id`, unique within the instrument, and its `text`. Item IDs name the question, not the column: the same item is `ems_1` in every wave even if the column is `ems_1_w1` in one file and `ems_1_w2` in the next. The column map makes that link.

An item's `type` is one of:

- `choice` (the default): answered with one of the response options.
- `number`: an amount, such as an age or a feature value. `min` and `max` give the allowed range.
- `text`: an open answer. labcatalog never shows or exports open answers, since they can identify people; it only counts them.

For a pipeline's features, every item is a `number` and its text says what it is:

```yaml
items:
  - {id: frontal_alpha_asymmetry, label: Frontal alpha asymmetry, text: "Frontal alpha asymmetry: log alpha power at F4 minus F3", type: number, min: -3, max: 3}
  - {id: epochs_kept, label: Clean epochs, text: "Clean two-second epochs kept, out of 60", type: number, min: 0, max: 60}
```

Number items can be used directly in correlations, regressions and multilevel models, without a score. A `label` gives an item a short name for those tables and the text written from them; without one, the item's full text is used.

## Response sets

A response set is a named list of options, each with the `value` stored in the data and the `label` the respondent saw. Items use `default_response_set` unless they name another with `response_set`. A value in the data that is neither an option nor a missing code is reported as a problem.

## Scores

A score combines items:

| Key | Meaning |
|---|---|
| `id`, `label` | The score's ID and its name, such as Total or Anxiety. |
| `method` | `sum` or `mean`. |
| `items` | The item IDs in the score. |
| `missing_rule` | What to do when items are missing (below). |
| `min_valid` | The fewest answered items that still give a score. |

The missing rules:

- `complete` (the default): no score unless every item is answered.
- `prorate`: the mean of the answered items times the number of items, when at least `min_valid` items are answered. A `mean` score is the mean of the answered items.
- `zero`: missing items count as 0.

Items marked `reverse: true` are reversed before scoring, using their response options: on a 0 to 3 scale, 0 becomes 3 and 3 becomes 0. If the data already hold the reversed values, set `reversed_in_data: true` on the administration (see [Column Maps and Overrides](variable-maps.md)).

labcatalog computes every score itself from the items. If your data also contain a score your lab computed, map that column to `score:<id>` and labcatalog reports every row where the two disagree.

## References and license

`references` lists the instrument's references by their key in `references.bib`, each with an optional `pdf`, a path inside the references folder. `license` says how the instrument may be used. Both are shown on the instrument's page, and the Instruments list flags instruments that have neither.

## Custom fields and tags

A lab often wants its own fields, such as a domain for each instrument or topics for each score. Declare them in `labcatalog.yaml`:

```yaml
custom_fields:
  - {name: domain, label: Domain, applies_to: instrument, type: choice, choices: [emotion, family, health, media]}
  - {name: topics, label: Topics, applies_to: score, type: tags, choices: [negative affect, positive affect, sleep]}
```

and fill them in under `custom`:

```yaml
custom:
  domain: emotion
scores:
  - {id: ems_sadness, label: Sadness, method: sum, items: [ems_2, ems_6, ems_7], custom: {topics: [negative affect]}}
```

A field can apply to an `instrument`, a `score`, an `item`, an `administration`, a `dataset` or a `study`, and be `text`, `number`, `date`, `choice` or `tags`. An item's values go under its own `custom` in the instrument file, and a study's under `studies.<study>.custom` in `labcatalog.yaml`. Choice and tags fields can be added to the filters on the Instruments page with `browse.facets`. A filter on a score or item field finds the instruments with such a score or item, and one on a study field finds the instruments given in that study. A field can also take its choices from a vocabulary that comes with labcatalog; [Tag Scores with RDoC](../how-to/tag-rdoc.md) uses the RDoC domains and constructs.
