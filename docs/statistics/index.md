# Statistics

labcatalog computes the statistics most papers report: reliability (Cronbach's α, McDonald's ω, item-rest correlations), confirmatory factor analysis and measurement invariance across waves, reporters and groups, correlations, regression, *t* tests and ANOVA, multilevel models, and attrition analyses. It uses established packages rather than its own formulas, and its defaults follow [JASP](https://jasp-stats.org/), so its numbers match what JASP gives with its default options.

## R first, Python second

When R is set up on the Settings page (see [Set Up R and Language Models](../how-to/r-and-models.md)), the analyses on the Analysis and Methods pages and the factor models run in R. Without R, or when R fails, the same analyses run in Python, and each result says which one computed it. The descriptive statistics and reliability on the instrument pages are always computed in Python.

| | R | Python |
|---|---|---|
| Reliability, correlations, regression, group comparisons | psych, effectsize, MBESS | scipy, statsmodels |
| Correlations and regressions within studies, for datasets of several studies | stats (lm) | statsmodels |
| Confirmatory factor analysis, ω | lavaan, semTools | semopy |
| Measurement invariance across waves, reporters and groups, score tests | lavaan, semTools | not available |
| Multilevel models | lme4, lmerTest, performance | statsmodels |
| Mediation, with up to two moderators | lavaan; modsem for latent interactions | not available |
| Multiple imputation, pooled correlations, regressions and group comparisons | mice, miceadds | not available |
| Rater agreement: Cohen's κ, intraclass correlations | psych | statsmodels (κ only) |
| Cross-lagged panel models (RI-CLPM, CLPM) | lavaan | not available |

## Settings that change the numbers

These settings are in `labcatalog.yaml`, under `stats`, so everyone who opens the project gets the same results:

```yaml
stats:
  decimals: 2              # 1 to 4; p values keep three
  correlation: pearson     # pearson or spearman
  t_test: welch            # welch or student
  cfa_estimator: wlsmv     # wlsmv (items as ordered categories), ml or mlr (items as continuous)
  correlate_by: id         # id, the group's name, or none
  missing: available       # available (everyone with values) or impute (multiple imputation)
  imputations: 20          # imputed data sets
  seed: 1                  # the imputation's random seed
```

- `correlation` sets the coefficient of the correlations between scores and variables. Item-rest correlations and regression always use Pearson.
- `t_test` sets the test that compares two groups.
- `cfa_estimator` sets how factor models and invariance tests treat the items.
- `decimals` sets the decimal places of the numbers in tables and paragraphs.
- `missing` sets whether the Analysis page's sections use everyone with values (`available`) or multiple imputation (`impute`), with `imputations` imputed data sets drawn from `seed`. See [Analysis](../app/analysis.md#multiple-imputation).
- `invariance_free` lists the items an invariance test lets differ (partial invariance). It is written by the invariance tables' **Save and rerun**; see [Instruments](../app/instruments.md).
- `correlate_by` sets how people in different datasets are matched, for example a parent and their child through their family. See [IDs, Groups and Missing Codes](../concepts/ids-groups-missing.md).

The Settings page sets these under **This project** and saves them here. They are where each page starts: a switch on a section of the Analysis page (the coefficient of the correlation table, the test of the group comparison) or on the factor model and invariance panels tries another for what that section shows, without changing the project, and the table notes say which was used.

## Get the code

Every analysis has a **Code** section with R and Python code that reproduces it from the data files, and draws its chart again with ggplot2 or matplotlib where it has one. The factor models and invariance tests on the instrument pages, and the mediation models on the Analysis page, are saved as Mplus inputs as well; see [Instruments](../app/instruments.md) and [Analysis](../app/analysis.md). Use them to rerun an analysis outside labcatalog, extend it, or share it with a co-author or reviewer.
