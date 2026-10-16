# Instruments

The Instruments page lists every instrument. Click one to open its page: items and options, scores and their reliability, how they change across waves, factor structure, and code to score them.

## The list

On the left:

- **Search** finds instruments by ID, name, abbreviation, construct or custom field. Tick **Also search item text** to search the wording of the items too.
- The filters narrow the list by study, wave, reporter and any field set in `browse.facets`. Values within one filter combine with "or", different filters with "and". The number beside each value is how many instruments it would show. **Clear filters** clears them.

The table shows each instrument's abbreviation, name, construct, reporters, number of items, and how many people answered it in each dataset the filters show. The **Missing** column lists what the catalog still lacks for an instrument, such as its scores, reference or license.

### Ask the language model

With a language model set up (see [Set Up R and Language Models](../how-to/r-and-models.md)), **Ask the language model** finds instruments from a description in your own words, such as "trouble falling asleep". It sends the instruments' names and item wording, never any data. The answer lists the matching instruments and items with the model's reasons, and narrows the list until you press **Clear**.

### Export

Tick instruments in the table and press **Export** to write their variables, data and statistics to `outputs/`. See [Export Variables and Data](../how-to/export-data.md).

## An instrument's page

The top shows the instrument's name, abbreviation, construct, who reported on whom, its instructions, references with their PDF (**View PDF** shows it in the page, **Open** in your PDF viewer), its license, and what is missing from the catalog. **All instruments** goes back to the list.

### Items

The items with their wording, whether they are reversed, and the column that holds each one in every dataset. Beside them, the response options and the missing codes.

### Scores

A table of every score in every wave: *N*, mean, *SD*, median, observed and possible range, Cronbach's α, McDonald's ω (once the factor models are done) and how many people answered every item. Below it:

- Box plots of the scores in each wave, and the distribution of the total score.
- **Scores across waves**: the mean of each score in each wave, for everyone and for the people who took part in every wave.
- **Stability across waves**: the correlation of the same people's scores one wave apart.
- **Invariance across waves**: whether the score measures the same thing in each wave (configural, metric and scalar invariance). It needs R.
- **Against other scores**: how this score correlates with every other score measured in the same wave.

### Item analysis

How the items were answered: the share of each option per item and wave, item means as radar charts, each wave against the others, item-total correlations with α without each item, and the correlations between items. For a demographics instrument, a table of the sample in each wave.

### One dataset

Pick a dataset to see the instrument in that file alone:

- **Items in** the dataset: valid answers, missing codes and values that are not options, per item.
- **Factor structure**: a confirmatory factor analysis of the scores' items, with fit indices, standardized loadings and ω. Without R, it is fitted in Python with the items as continuous; with R, it follows `stats.cfa_estimator`.
- **Measures paragraph**: a draft paragraph for the paper, with α and ω in this dataset, and a **Copy text** button. With a language model and the reference PDF, **Draft the description from the reference PDF** drafts the instrument's `description` for you to check.
- **Everyone's answers**, **Answers by participant** and **Standardized scores**: each person's answers and scores, to spot unusual response patterns.
- **Scoring code**: R and Python code that computes the scores from this data file.
- **Scoring script from the reference PDF**: with a language model, **Write with the language model** writes scoring scripts from the instrument's manual, saved in `scoring/`, to compare with labcatalog's own scoring.

### History

If the project is in git, every commit that changed the instrument's file, with what changed.
