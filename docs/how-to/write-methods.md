# Write the Methods Section

Much of a methods section restates what the catalog already knows: how many people took part in each wave, what each instrument measures and how it is scored, how reliable it was in this sample. The **Methods** page drafts that text from the catalog, so the numbers in it always match the data. Copy it into your manuscript and edit it there.

## Pick the study and wave

At the top of the page, pick the study and, for a study with several waves, the wave. The Participants text covers every wave; Table 1 and the Measures paragraphs describe the wave you pick.

## Participants

The Participants part has a paragraph and two tables:

- The paragraph says how many people took part in each wave, how many returned, and, when the study has several modalities, how many have data from each and how many of those had them again at the next wave that collected that modality.
- **Participants by Wave** counts people per reporter and wave, and how many returned from the previous wave. With a group, it also counts groups and the groups with data from every reporter.
- **Participants by Modality** counts people per modality and wave.

Below them, **Table 1** describes the sample on the variables you choose, such as age, gender and the main scores, as *M* (*SD*) or *n* (%).

## Attrition

To compare those who stayed with those who left, pick a wave other than the last at the top of the page and choose the variables to compare. The **Attrition** section tests whether the people in that wave who returned at the next wave differed from those who did not: a *t* test for numbers and scores, a χ² test for choices. It writes a sentence for the paper and a table, both with a copy button.

## Procedure

The Procedure part shows how each modality's data were collected and processed, taken from `methods` in the study's file in `studies/`. labcatalog cannot know this; you write it once per study, and it then appears here and on the Datasets page.

## Measures

The Measures part has one paragraph per instrument given in the chosen wave: its name and reference, what it measures, how many items it has and how they are answered, which items are reversed, how it is scored, and Cronbach's α and McDonald's ω in this wave's data. The **description** of the instrument, a sentence or two written by a person, fills the middle of the paragraph.

## Change the wording

Both paragraphs come from templates with placeholders in braces. To change the wording for the whole project, set a template in `labcatalog.yaml`:

```yaml
measures: "We used {named}. {description} {items} {reverse} {scoring} {alpha} {omega}"
participants: "{waves} {counts} {demographics} {retention} {modalities}"
```

An instrument can have its own `measures` template, and a study its own `participants` template in its file in `studies/`.

| Template | Placeholders |
|---|---|
| `measures` | `name`, `abbreviation`, `cite`, `named`, `construct`, `reporter`, `n_items`, `scale`, `description`, `items`, `reverse`, `scoring`, `alpha`, `omega` |
| `participants` | `study`, `n_waves`, `waves`, `counts`, `demographics`, `retention`, `modalities` |

`counts`, `retention` and `modalities` name each reporter ("191 parent and 182 child respondents"); in a study with one reporter they leave the word out ("30 respondents").

`demographics` gives a sentence for each reporter with blanks, `[ ]`, for the shares of women or girls and of men or boys and the mean age and its SD. labcatalog leaves these to you: which people and which wave they describe, and where age and gender come from, differ from one study to the next. Fill them in after copying the paragraph, or write your own sentence in the template in place of `{demographics}`.

`labcatalog validate` reports a placeholder it does not know.
