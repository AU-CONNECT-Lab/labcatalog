# Analysis

The Analysis page runs the analyses most papers need on the datasets you choose: a correlation table, regressions, a group comparison and a multilevel model, each on its own tab beside the Sample. Each result is a table ready for a manuscript, with a chart, a **Copy table** button, **Save to outputs**, and a **Code** section with the R and Python code that reproduces it. A note under each result says whether it was computed in R or in Python. The correlation table, the regressions and the group comparison also write a **Results paragraph** in APA style, with a **Copy text** button: the significant correlations (each pair when there are three or fewer, otherwise the five strongest), each predictor's *b*, *SE*, *p* and *R*², or the groups' means with the test and its effect size. Significance is *p* < .05, and the numbers have the decimal places set on the Settings page. With a language model set up (see [Set Up R and Language Models](../how-to/r-and-models.md)), **Interpret with the language model** under any Results paragraph, here or on an instrument's page, asks the model for a short interpretation of the result and a list of things to check. It sends the tables and the paragraph, never any data, and its answer is a draft to check against the tables.

![The Analysis page with a correlation table](../images/app/analysis.png)

## Sample

The Sample on the left applies to every tab except the multilevel model.

- **Datasets**: the data files to analyze. By default, every dataset of the first wave of the first study.
- **Only people in every selected dataset**: on (the default) keeps the people who are in all of them; off keeps everyone in any of them.
- **Measures**: the instruments whose scores and numbers appear in the lists below, the multilevel model included. By default, all of them. The **Select** menu next to it can choose all, all of one modality, or none.

The note below says how many people are in the sample and how they were matched across files: by ID, or by group when `stats.correlate_by` names one. Rows whose ID repeats within a file are left out. When a file holds several people of one group (two children of a family), that group is taken person by person, as described under [Groups](../concepts/ids-groups-missing.md#groups), and the note says how many groups that affects.

The variable lists hold every score and number item of the chosen measures in the chosen datasets, labeled with their wave. Type in a list to filter it.

## Correlation table

Choose the **Variables**; by default, every score of the chosen measures, without the number items. The **Select** menu adds all variables, all of one wave or all of one modality.

The table lists each variable's *n*, *M* and *SD* and the correlation of every pair, with stars for *p* < .05, .01 and .001. Each pair uses everyone with both values. The coefficient is Pearson's *r*, or Spearman's ρ when `stats.correlation` is `spearman`. With three or more variables, a chart above the table shows the correlations as a **Heatmap** or as **Dots**.

## Regression

Choose one or more predictors (**X**) and an outcome (**Y**). Each predictor gets its own simple regression on everyone with both values. The table gives *n*, *r* with its 95% CI, *p*, the slope and intercept with their standard errors, and *R*². The chart plots the outcome against each predictor with its fit line, the distributions on the margins and the residuals in an inset. Hover over a point to see the person's ID.

## Group comparison

Choose the **Groups**, an answer-option item of a demographics instrument, and the **Outcome**. Groups with fewer than two people are left out. With two groups, the test is Welch's *t* test, or Student's when `stats.t_test` is `student`, with Cohen's *d* and the mean difference, each with a 95% CI. With three or more, it is a one-way ANOVA with η² and ω². The page shows a table of *n*, *M* and *SD* per group, the test table, and a box plot with every person as a point.

## Measurement invariance across groups

Choose an **Instrument** in one of the chosen datasets and the **Groups**, an answer-option item of a demographics instrument, then press **Test**. labcatalog fits a multigroup factor model in R with one group per answer and tests configural, threshold (for ordered items), metric and scalar invariance, the same steps as across waves on the instrument page. The grouping item may be in another dataset, such as the child's gender reported by the parent; people are matched as in the Sample. A group needs more people than the model has items, and smaller groups are left out and named. **Which items differ** and **Save and rerun** work as on the instrument page, with the freed items stored for this grouping item.

## Mediation

Choose X, the mediator M and the outcome Y from the scores and numbers of the Sample, and any covariates, which predict both M and Y. A **Moderator W** is optional; tick the paths it moderates: a (X to M), b (M to Y) or c′ (X to Y, the direct effect). The diagram shows the model as chosen. **Fit** runs it in R with lavaan, on everyone with all its values; with a moderator, X, M and W are centred at their means and the conditional effects are taken at W's two answers or at its mean and 1 SD either side. The table gives each path, the indirect effect (a × b) and, without a moderator, the total effect; with a moderator, the conditional indirect and direct effects and, when only a or only b is moderated, the index of moderated mediation. With **Bootstrap**, confidence intervals are percentile bootstrap intervals; set the number of **Bootstrap resamples** (1000 by default). With **None**, they are Wald intervals (by the delta method for the indirect and other defined effects), which take seconds. **ML** or **MLR** sets the estimator: bootstrapping needs plain maximum likelihood, whose estimates are the same as MLR's, so with Bootstrap MLR changes only the fit test; with None, MLR also gives robust standard errors. **Scores** or **Items** sets what the variables are. With Scores, X, M, Y and W are the scores themselves. With Items, X, M and Y must be scores with two or more items, and each becomes a factor of its items (the first item's loading fixed at 1); a moderator that is a score becomes a factor too, and one that is a number or an answer stays observed. Their items must not overlap, so a total and one of its subscales cannot both be factors. Without a moderator the item model runs in lavaan and offers WLSMV, which treats the items as ordered categories (its bootstrap refits by DWLS, whose estimates are WLSMV's). With a moderator it runs in modsem, which fits the latent interaction by LMS, or by QML when the moderator is observed, with the items as continuous; there is then no chi-square test of fit, and each bootstrap resample refits the whole model, so 1000 resamples take several minutes. The table's β column is fully standardized; effects taken at values of W have none. The **Results paragraph** reports the numbers, and **Code** holds the R script, which Save to outputs writes with the data. Mediation needs R, and the Items mode with a moderator needs the R package modsem; the number of R processes for the resamples is on the Settings page.

## Script

**Write script** writes the correlations, regression and group comparison, as currently chosen on their tabs, as one R script and one Python script. **Save to outputs** saves them with the data as `analysis_data.csv`, so either script runs in that folder.

## Multilevel model

A linear mixed model of one outcome across waves. This section picks its own waves and keeps everyone with at least one; the Sample does not apply, except for **Measures**.

- **Outcome**: a score or number item. By default, the first total score measured in two or more waves.
- **Waves**: the datasets that hold the outcome, one per wave, from one study. By default, all of them.
- **Covariates**: a variable from one dataset, used at every wave, or a variable marked "(each wave)", which uses each wave's own value.
- **Time counts**: **Waves since the first** (the default) counts the waves since the first chosen wave; a wave you leave out still counts, so waves 1 and 3 give times 0 and 2. **Months, from the dates** and **Years, from the dates** count the time from the earliest visit date in the first chosen wave to each visit, from each dataset's `date_column`, so people seen early or late in a wave get their own times. Every chosen dataset needs a `date_column`; rows without a readable date are left out.
- **Waves within people**: people as a level, with time as set above. On by default.
- **People within each** group: groups as a level, when `labcatalog.yaml` names a group under `ids`. Off by default.
- **Random slope of time for each person**: on by default.
- **Split each-wave covariates into person mean and deviation**: separates the effect between people from the effect within a person. Shown when an each-wave covariate is chosen.

The results are three tables: **Fixed Effects** (*b*, *SE*, *df*, *t*, *p* and 95% CI; with Satterthwaite's *df* in R), **Random Effects** (variances, SDs and the slope-intercept correlation) and **Model Summary** (the ICC of each level, the numbers of observations, people and groups, and fit statistics). A warning appears when the fit is singular, that is, when a random effect cannot be estimated from these data; a simpler model, such as one without the random slope, may then fit.

Under them, a **Results paragraph** with a **Copy text** button gives the model's design and sample, the ICC, each fixed effect and the SD of each random effect. Below that, a chart of the trajectories draws each person's values across the waves as thin lines, each wave's mean as a circle, and the fixed effects' prediction (intercept plus time) as a thick line. With time from the dates, the axis counts months or years. With covariates in the model, the line is the prediction for the mean of each number covariate and the reference option of each answer covariate.

**Save to outputs** writes the tables, the chart, the R and Python code, and `multilevel_data.csv`, with one row per person and wave.

## Saved files

Every **Save to outputs** on this page writes a new folder in `outputs/` with the tables as `.csv`, `.docx` and `.tex`, the chart as `.png` and `.svg`, the data and the R and Python scripts, and `manifest.json`. See [Copy Tables into a Manuscript](../how-to/copy-tables.md).
