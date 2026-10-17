# Study Files

One file per study in `studies/`. `study` is required and must be a study under `studies` in `labcatalog.yaml`. See [Column Maps and Overrides](../concepts/variable-maps.md).

```yaml
# yaml-language-server: $schema=../schemas/study.schema.json
study: my_study
administrations:
  - {instrument: parent_stress, datasets: [parent_w1, parent_w2], target: self}
```

## Top level

| Key | Type | Meaning |
|---|---|---|
| `study` | text | The study's ID. Required. |
| `methods` | mapping | Each modality to a paragraph on how its data were collected and processed. A key can also be the name of one of the study's datasets, whose text then replaces its modality's for that dataset. |
| `participants` | text | This study's own Participants template. |
| `administrations` | list | Which instruments were given in which datasets. |

## administrations

| Key | Type | Default | Meaning |
|---|---|---|---|
| `instrument` | text | | The instrument's ID. Required. |
| `datasets` | list of text | | The datasets it was given in. Required. |
| `target` | text | | Who it is about; one of `vocab.targets`. |
| `abbreviation` | text | | The name this study used for it. |
| `reversed_in_data` | true or false | `false` | Reverse-keyed items are already reversed in the data. |
| `overrides` | list | | Changes to single items. |
| `custom` | mapping | | Values of custom fields that apply to administrations. |

## overrides

| Key | Type | Default | Meaning |
|---|---|---|---|
| `item` | text | | The item's ID. Required. |
| `dataset` | text | every dataset | Only this dataset. |
| `text` | text | | The wording used. |
| `response_set` | text | | Another response set of the instrument. |
| `dropped` | true or false | `false` | The item was not asked. |
