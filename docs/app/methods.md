# Methods

The Methods page drafts the parts of a methods section that the catalog already knows. Pick the study and the wave at the top: the Participants part covers every wave of the study, while Table 1, Attrition and Measures describe the wave you pick. Every paragraph has a **Copy text** button and every table a **Copy table** button. See [Write the Methods Section](../how-to/write-methods.md) for how to use it in a paper and how to change the wording.

![The Methods page with the Participants paragraph](../images/app/methods.png)

## Participants

- A paragraph on the waves, how many people took part in each, how many returned, and how many have data from each modality.
- **Participants by Wave**: people per reporter and wave, how many returned from the previous wave, and, with a group, the number of groups and the groups with data from every reporter.
- **Participants by Modality**: people per modality and wave, and how many of them came back from the last wave that collected that modality; shown when the study has two or more modalities.

## Table 1

Choose the **Variables**; by default, the demographics items and each instrument's total score. The table describes everyone with data in the chosen wave, one column per dataset: *M* (*SD*) for numbers and scores, *n* (%) for each answer option, and Cronbach's α for scores.

## Attrition

Compares the people in the chosen wave who took part again in the next wave with those who did not, on the variables you choose: *t* tests with Cohen's *d* for numbers and scores, χ² tests for answer options. It writes a sentence and a table. A variable held in more than one file of the wave, such as the same scale answered by two reporters, gets a row for each file. Pick a wave other than the last to see it.

## Procedure

How each modality's data were collected and processed in the chosen wave, from `methods` in the study file. A dataset with its own text there (keyed by its name) uses it instead of its modality's; when the datasets of one modality differ, each text is headed by the datasets it covers.

## Measures

A paragraph for each instrument given in the chosen wave, with its reliability in that wave. The ω values fill in when the factor models finish.
