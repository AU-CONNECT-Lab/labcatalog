# Overview

The Overview page shows the project at a glance.

![The Overview page of the example project](../images/app/overview.png)

## Summary

The number of instruments and datasets, the studies, waves and reporters, and the number of errors and warnings. Click the instruments to open the Instruments page, or the errors and warnings to open the Problems page.

## Timeline

Each wave as a bar from its start to its end date, with the number of people per reporter. A wave without an end date is still collecting: its bar runs to today, the count is compared with the previous wave's, and a faint bar shows when it would end if it took as long as the previous wave. The `milestones` of each study are shown as diamonds, and a dashed line marks today.

## Collection pace

For each reporter, how many rows had come in by each week since each wave started, one line per wave. It needs a `date_column` on the datasets. Use it to see whether a wave is collecting faster or slower than the last.

## Scores in each wave

Every score's mean in each wave, as a share of its possible range, so scores on different scales can be compared. One row per score, one dot per wave. **Instruments** picks which instruments are shown; a project with more than 15 starts with the first 15.

## How the scores relate

A network of the scores measured in one wave: scores that correlate at |*r*| ≥ .30 are linked, red for positive and blue for negative, thicker for stronger. Drag the nodes and scroll to zoom. Above the chart:

- **Instruments**: which instruments' scores to show.
- **Wave**: which wave.
- **Color by**: color the scores by instrument, by clusters of scores that correlate with each other, or by a filter such as reporter or a custom field.

The coefficient is Pearson's *r*, or Spearman's ρ when `stats.correlation` is `spearman`. `stats.correlate_by: none` turns this chart off.
