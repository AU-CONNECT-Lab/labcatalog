# Instruments

The Instruments page lists every instrument. Click one to open its page: items and options, scores and their reliability, how they change across waves, factor structure, and code to score them.

![The Instruments page listing the example's instruments](../images/app/instruments.png)

## The list

On the left:

- **Search** finds instruments by ID, name, abbreviation, construct, custom field or the name of a data column mapped to them. Tick **Also search item text** to search the wording of the items too.
- The filters narrow the list by study, wave, reporter, who the instrument is about, modality and the `choice` and `tags` custom fields, or by the list set in `browse.facets`. **Given in** finds instruments given in every wave of their study, or in fewer. **Catalog** finds instruments that are complete or still lack something, such as scores or a license, and those not yet in any dataset. A filter with only one value is hidden. Values within one filter combine with "or", different filters with "and". The number beside each value is how many instruments it would show. The chosen values appear above the table, where × removes one; **Clear** clears them all.

The table shows each instrument's abbreviation, name, construct, reporters, number of items, and how many people answered it in each dataset the filters show. The **Missing** column lists what the catalog still lacks for an instrument, such as its scores, reference or license.

### Ask the language model

With a language model set up (see [Set Up R and Language Models](../how-to/r-and-models.md)), **Ask the language model** finds instruments from a description in your own words, such as "trouble falling asleep". It sends the instruments' names and item wording, never any data. The answer lists the matching instruments and items with the model's reasons, and narrows the list until you press **Clear**.

### Add an instrument

**Add an instrument** walks through a new instrument in six steps: what it is (ID, name, abbreviation, kind, construct, description, references from `references.bib` with the PDF of each, license); its answer options, copied from an instrument with the same answers or typed in; its items, pasted one per line, with `(R)` at the end of a reverse-keyed item; its scores, starting from **Add a total score**; the datasets it was given in, where **Find the columns** guesses each item's column from the column names; and a last step that shows the lines each file gains before **Save**. It writes `instruments/<id>.yaml`, the rows of each dataset's column map and the administrations in the study files.

![The Items step of Add an instrument, with three pasted items, one of them reverse-keyed](../images/app/instrument-wizard.png)

On an instrument's page, **Complete this instrument** beside what is missing opens the same steps on that instrument, starting at the first step with something missing. Press a step's title to go straight to it; only **Check and save** is reached with **Next**. Lines of the file that are not changed stay as they were, comments included.

### Export

Tick instruments in the table and press **Export** to write their variables, data and statistics to `outputs/`. The dialog asks for the instruments, then the datasets by wave and reporter, then the layout. See [Export Variables and Data](../how-to/export-data.md).

![The Datasets step of Export, with datasets ticked by wave and reporter](../images/app/export.png)

## An instrument's page

The top shows the instrument's name, abbreviation, construct, who reported on whom, its instructions, references with their PDF (**View PDF** shows it in the page, **Open** in your PDF viewer), its license, and what is missing from the catalog. **Instruments** at the top goes back to the list.

![The page of the Example Mood Scale](../images/app/instrument.png)

### Items

The items with their wording, whether they are reversed, and the column that holds each one in every dataset. Beside them, the response options and the missing codes.

### Scores

A table of every score in every wave: *N*, mean, *SD*, median, observed and possible range, Cronbach's α, McDonald's ω (once the factor models are done) and how many people answered every item. Below it:

- Box plots of the scores in each wave, and the distribution of the total score.
- **Scores across waves**: the mean of each score in each wave, for everyone and for the people who took part in every wave.
- **Stability across waves**: the correlation of the same people's scores one wave apart.
- **Invariance across waves**: whether the score measures the same thing in each wave (configural, metric and scalar invariance). It needs R.
- **Invariance across reporters**: the same test between reporters who answered the instrument in the same wave, such as a parent and a child rating the child's mood. The reporters of one group are paired through `stats.correlate_by`, so this section appears only when that names a group.
- **Against other scores**: how this score correlates with every other score measured in the same wave.

Under each invariance table, a **Results paragraph** gives every step's fit and its change from the step before (Δχ², ΔCFI, ΔRMSEA), with a **Copy text** button; it reports the numbers and leaves the judgement of which step holds to you. **Which items differ** runs a score test for each item at the step you choose: how much the fit would improve if that item's loadings, thresholds or intercepts were free to differ. Tick the items to free and press **Save and rerun**; labcatalog writes them under `stats.invariance_free` in `labcatalog.yaml` and tests again with those items freed (partial invariance). The table note lists what is freed. To hold an item equal again, untick it in the same dialog.

### Item analysis

How the items were answered: the share of each option per item and wave, item means as radar charts, each wave against the others, item-total correlations with α without each item, and the correlations between items. For a demographics instrument, a table of the sample in each wave.

### One dataset

Pick a dataset to see the instrument in that file alone:

- **Items in** the dataset: valid answers, missing codes and values that are not options, per item.
- **Factor structure**: a confirmatory factor analysis of the scores' items, with fit indices (RMSEA with its 90% CI when fitted in R), standardized loadings and ω. Without R, it is fitted in Python with the items as continuous; with R, it follows `stats.cfa_estimator`. An instrument with three or more subscales gets two more models of a general factor over them: a second-order model (items on subscale factors, subscale factors on the general factor, as in JASP), with hierarchical ω (computed in R only), and a one-factor model of the subscale scores, which treats the scores as continuous. With exactly three subscales the second-order model fits the same as the subscale model and the subscale-scores model fits exactly, so only their loadings and ω say something new. A **Results paragraph** below the tables reports each model's fit indices, the range of its standardized loadings and ω, without judging the fit.
- **Measures paragraph**: a draft paragraph for the paper, with α and ω in this dataset, and a **Copy text** button. With a language model and the reference PDF, **Draft the description from the reference PDF** drafts the instrument's `description` for you to check.
- **Everyone's answers**, **Answers by participant** and **Standardized scores**: each person's answers and scores, to spot unusual response patterns.
- **Scoring code**: R and Python code that computes the scores from this data file.
- **Scoring script from the reference PDF**: with a language model, **Write with the language model** writes scoring scripts from the instrument's manual, saved in `scoring/`, to compare with labcatalog's own scoring.

### History

If the project is in git, every commit that changed the instrument's file, with what changed.
