# Analysis

The Analysis page runs the analyses most papers need on the datasets you choose: a correlation table, regressions, a group comparison and a multilevel model. Each result is a table ready for a manuscript, with a chart, a **Copy table** button, **Save to outputs**, and a **Code** section with the R and Python code that reproduces it. A note under each result says whether it was computed in R or in Python.

## Sample

The choices here apply to every section of the page except the multilevel model.

- **Datasets**: the data files to analyze. By default, every dataset of the first wave of the first study.
- **Only people in every selected dataset**: on (the default) keeps the people who are in all of them; off keeps everyone in any of them.
- **Measures**: the instruments whose scores and numbers appear in the lists below, the multilevel model included. By default, all of them. The **Select** menu next to it can choose all, all of one modality, or none.

The note below says how many people are in the sample and how they were matched across files: by ID, or by group when `stats.correlate_by` names one. Rows whose ID repeats within a file are left out.

The variable lists hold every score and number item of the chosen measures in the chosen datasets, labeled with their wave. Type in a list to filter it.

## Correlation table

Choose the **Variables**; by default, the total score of each instrument. The **Select** menu adds all variables, all of one wave or all of one modality.

The table lists each variable's *n*, *M* and *SD* and the correlation of every pair, with stars for *p* < .05, .01 and .001. Each pair uses everyone with both values. The coefficient is Pearson's *r*, or Spearman's ρ when `stats.correlation` is `spearman`. With three or more variables, a chart beside the table shows the correlations as a **Heatmap** or as **Dots**.

## Regression

Choose one or more predictors (**X**) and an outcome (**Y**). Each predictor gets its own simple regression on everyone with both values. The table gives *n*, *r* with its 95% CI, *p*, the slope and intercept with their standard errors, and *R*². The chart plots the outcome against each predictor with its fit line, the distributions on the margins and the residuals in an inset. Hover over a point to see the person's ID.

## Group comparison

Choose the **Groups**, an answer-option item of a demographics instrument, and the **Outcome**. Groups with fewer than two people are left out. With two groups, the test is Welch's *t* test, or Student's when `stats.t_test` is `student`, with Cohen's *d* and the mean difference, each with a 95% CI. With three or more, it is a one-way ANOVA with η² and ω². The page shows a table of *n*, *M* and *SD* per group, the test table, and a box plot with every person as a point.

## Script

**Write script** writes the correlations, regression and group comparison above, as currently chosen, as one R script and one Python script. **Save to outputs** saves them with the data as `analysis_data.csv`, so either script runs in that folder.

## Multilevel model

A linear mixed model of one outcome across waves. This section picks its own waves and keeps everyone with at least one; the Sample above does not apply, except for **Measures**.

- **Outcome**: a score or number item. By default, the first total score measured in two or more waves.
- **Waves**: the datasets that hold the outcome, one per wave, from one study. By default, all of them.
- **Covariates**: a variable from one dataset, used at every wave, or a variable marked "(each wave)", which uses each wave's own value.
- **Waves within people**: people as a level, with time as the waves since the first. On by default.
- **People within each** group: groups as a level, when `labcatalog.yaml` names a group under `ids`. Off by default.
- **Random slope of time for each person**: on by default.
- **Split each-wave covariates into person mean and deviation**: separates the effect between people from the effect within a person. Shown when an each-wave covariate is chosen.

The results are three tables: **Fixed Effects** (*b*, *SE*, *df*, *t*, *p* and 95% CI; with Satterthwaite's *df* in R), **Random Effects** (variances, SDs and the slope-intercept correlation) and **Model Summary** (the ICC of each level, the numbers of observations, people and groups, and fit statistics). A warning appears when the fit is singular, that is, when a random effect cannot be estimated from these data; a simpler model, such as one without the random slope, may then fit.

**Save to outputs** writes the tables, the R and Python code, and `multilevel_data.csv`, with one row per person and wave.

## Saved files

Every **Save to outputs** on this page writes a new folder in `outputs/` with the tables as `.csv`, `.docx` and `.tex`, the chart as `.png` and `.svg`, the data and the R and Python scripts, and `manifest.json`. See [Copy Tables into a Manuscript](../how-to/copy-tables.md).
