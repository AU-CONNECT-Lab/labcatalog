# Statistics

labcatalog computes the statistics most papers report: reliability (Cronbach's α, McDonald's ω, item-rest correlations), confirmatory factor analysis and measurement invariance across waves, reporters and groups, correlations, regression, *t* tests and ANOVA, multilevel models, and attrition analyses. It uses established packages rather than its own formulas, and its defaults follow [JASP](https://jasp-stats.org/), so its numbers match what JASP gives with its default options.

## R first, Python second

When R is set up on the Settings page (see [Set Up R and Language Models](../how-to/r-and-models.md)), the analyses on the Analysis and Methods pages and the factor models run in R. Without R, or when R fails, the same analyses run in Python, and each result says which one computed it. The descriptive statistics and reliability on the instrument pages are always computed in Python.

| | R | Python |
|---|---|---|
| Reliability, correlations, regression, group comparisons | psych, effectsize, MBESS | scipy, statsmodels |
| Confirmatory factor analysis, ω | lavaan, semTools | semopy |
| Measurement invariance across waves, reporters and groups, score tests | lavaan, semTools | not available |
| Multilevel models | lme4, lmerTest, performance | statsmodels |
| Mediation, with an optional moderator | lavaan; modsem for latent interactions | not available |

## Settings that change the numbers

These settings are in `labcatalog.yaml`, under `stats`, so everyone who opens the project gets the same results:

```yaml
stats:
  correlation: pearson     # pearson or spearman
  t_test: welch            # welch or student
  cfa_estimator: wlsmv     # wlsmv (items as ordered categories), ml or mlr (items as continuous)
  correlate_by: id         # id, the group's name, or none
```

- `correlation` sets the coefficient of the correlations between scores and variables. Item-rest correlations and regression always use Pearson.
- `t_test` sets the test that compares two groups.
- `cfa_estimator` sets how factor models and invariance tests treat the items when a page opens; a switch on the Factor structure and invariance panels changes it for what that page shows, and the table notes say which was used.
- `invariance_free` lists the items an invariance test lets differ (partial invariance). It is written by the invariance tables' **Save and rerun**; see [Instruments](../app/instruments.md).
- `correlate_by` sets how people in different datasets are matched, for example a parent and their child through their family. See [IDs, Groups and Missing Codes](../concepts/ids-groups-missing.md).

The number of decimal places is a setting of your computer, on the Settings page.

## Get the code

Every analysis has a **Code** section with R and Python code that reproduces it from the data files, and the Analysis page's **Script** section writes one script for the whole page. The factor models on the instrument pages are saved as Mplus inputs as well; see [Instruments](../app/instruments.md). Use them to rerun an analysis outside labcatalog, extend it, or share it with a co-author or reviewer.
