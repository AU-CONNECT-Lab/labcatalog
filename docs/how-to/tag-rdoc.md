# Tag Scores with RDoC

The Research Domain Criteria (RDoC; Insel et al., 2010) sort what a measure taps into domains, such as Negative Valence Systems, and constructs within them, such as Potential Threat ("Anxiety"). labcatalog has no RDoC list of its own: two [custom fields](../concepts/instruments.md) on scores carry the tags, and the filters on the Instruments page and **Color by** on the Overview network work with them like any other field. The same steps work for any other framework your lab tags with.

## Add the fields

Paste this into `labcatalog.yaml`. The choices are the domains and constructs of the RDoC matrix as NIMH listed them in October 2026; check the matrix for changes, and add subconstructs to the choices if you tag at that level.

```yaml
custom_fields:
  - name: rdoc_domain
    label: RDoC domain
    applies_to: score
    type: tags
    choices:
      - Negative Valence Systems
      - Positive Valence Systems
      - Cognitive Systems
      - Social Processes
      - Arousal and Regulatory Systems
      - Sensorimotor Systems
  - name: rdoc_construct
    label: RDoC construct
    applies_to: score
    type: tags
    choices:
      - Acute Threat ("Fear")
      - Potential Threat ("Anxiety")
      - Sustained Threat
      - Loss
      - Frustrative Nonreward
      - Reward Responsiveness
      - Reward Learning
      - Reward Valuation
      - Attention
      - Perception
      - Declarative Memory
      - Language
      - Cognitive Control
      - Working Memory
      - Affiliation and Attachment
      - Social Communication
      - Perception and Understanding of Self
      - Perception and Understanding of Others
      - Arousal
      - Circadian Rhythms
      - Sleep-Wakefulness
      - Motor Actions
      - Agency and Ownership
      - Habit - Sensorimotor
      - Innate Motor Patterns

browse:
  facets: [study, wave, reporter, rdoc_domain, rdoc_construct]
```

If `labcatalog.yaml` already has `custom_fields` or `browse`, add the two fields to the list and the two names to `facets` instead of pasting a second copy.

## Tag a score

Under each score in an instrument file, list its domains and constructs under `custom`. Tags are lists, so a score can sit in more than one:

```yaml
scores:
  - id: worry
    label: Worry
    method: sum
    items: [q3, q5, q8]
    custom:
      rdoc_domain: [Negative Valence Systems, Arousal and Regulatory Systems]
      rdoc_construct: [Potential Threat ("Anxiety"), Sleep-Wakefulness]
```

Tag scores rather than whole instruments: the subscales of one questionnaire often tap different constructs. On the Instruments page, a filter on a score's tag shows the instrument that holds the score. A tag that is not among the choices is reported as an error, which catches misspellings.

The tags are your lab's reading of each measure. labcatalog does not suggest them.

## Reference

Insel, T., Cuthbert, B., Garvey, M., Heinssen, R., Pine, D. S., Quinn, K., Sanislow, C., & Wang, P. (2010). Research Domain Criteria (RDoC): Toward a new classification framework for research on mental disorders. *American Journal of Psychiatry, 167*(7), 748–751.
