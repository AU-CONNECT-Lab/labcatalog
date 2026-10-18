# Tag Scores with RDoC

The Research Domain Criteria (RDoC; Insel et al., 2010) sort what a measure taps into domains, such as Negative Valence Systems, and constructs within them, such as Potential Threat ("Anxiety"). labcatalog comes with the RDoC domains and constructs as a vocabulary that a [custom field](../concepts/instruments.md) on scores can use. The filters on the Instruments page then list each construct under its domain, and **Color by** on the Overview network works with the field like any other.

## Add the field

Add one field to `labcatalog.yaml`, and its name to the filters:

```yaml
custom_fields:
  - {name: rdoc, label: RDoC, applies_to: score, type: tags, vocabulary: rdoc}

browse:
  facets: [study, wave, coverage, reporter, rdoc, status]
```

The vocabulary gives the field its choices: the six domains and the constructs of each, as NIMH listed them in October 2026. A field takes its choices from a vocabulary or from `choices`, not both. To tag at the level of subconstructs, or with another framework, declare a field with your own `choices` instead, as for any custom field.

If `labcatalog.yaml` already has `custom_fields` or `browse`, add the field to the list and its name to `facets` instead of pasting a second copy.

## Tag a score

Under each score in an instrument file, list its constructs under `custom`. Tags are lists, so a score can sit in more than one. A construct also counts as its domain, so choosing Arousal and Regulatory Systems in the filters finds the score below; tag a domain itself only when none of its constructs fits:

```yaml
scores:
  - id: worry
    label: Worry
    method: sum
    items: [q3, q5, q8]
    custom:
      rdoc: [Potential Threat ("Anxiety"), Sleep-Wakefulness]
```

Tag scores rather than whole instruments: the subscales of one questionnaire often tap different constructs. On the Instruments page, a filter on a score's tag shows the instrument that holds the score. A tag that is not among the choices is reported as an error, which catches misspellings.

The tags are your lab's reading of each measure. labcatalog does not suggest them.

## Reference

Insel, T., Cuthbert, B., Garvey, M., Heinssen, R., Pine, D. S., Quinn, K., Sanislow, C., & Wang, P. (2010). Research Domain Criteria (RDoC): Toward a new classification framework for research on mental disorders. *American Journal of Psychiatry, 167*(7), 748–751.
