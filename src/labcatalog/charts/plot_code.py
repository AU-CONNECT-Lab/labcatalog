import json

from labcatalog.charts import style

FIGURE_DPI = 300

R_SETUP = """\
# Figure: {what}, saved as {file} (ggplot2).
# Needs the R package ggplot2; install it once with: install.packages("ggplot2")
library(ggplot2)
"""
PYTHON_SETUP = """\
# Figure: {what}, saved as {file} (matplotlib).
# Needs matplotlib (pip install matplotlib).
import matplotlib.pyplot as plt
"""
R_SAVE = """\
if (interactive()) print(figure)
ggsave({file}, figure, width = {width}, height = {height}, dpi = {dpi}, bg = "white")
"""
PYTHON_SAVE = """\
fig.tight_layout()
fig.savefig({file}, dpi={dpi})
"""

R_CORRELATION_CELLS = """\
labels <- c({labels})
cells <- correlations
cells$x <- factor(labels[cells$x], levels = labels[-length(labels)])
cells$y <- factor(labels[cells$y], levels = rev(labels[-1]))
"""
R_HEATMAP = """\
figure <- ggplot(cells, aes(x, y, fill = r)) +
  geom_tile(colour = "white") +
  geom_text(aes(label = ifelse(is.na(r), "", sprintf("%.2f", r))), size = 3) +
  # RdBu with red for positive r, as on the Analysis page.
  scale_fill_distiller(palette = "RdBu", limits = c(-1, 1), name = {coefficient}) +
  coord_fixed() +
  labs(x = NULL, y = NULL) +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1), panel.grid = element_blank())
"""
R_DOTS = """\
figure <- ggplot(cells, aes(x, y)) +
  geom_point(aes(size = abs(r), colour = r)) +
  scale_size_area(max_size = 12, limits = c(0, 1), guide = "none") +
  scale_colour_distiller(palette = "RdBu", limits = c(-1, 1), name = {coefficient}) +
  coord_fixed() +
  labs(x = NULL, y = NULL) +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1))
"""
PYTHON_CORRELATION_CELLS = """\
labels = {{{labels}}}
names = list(labels)
grid = np.full((len(names) - 1, len(names) - 1), np.nan)
for row in correlations.itertuples():
    grid[names.index(row.y) - 1, names.index(row.x)] = row.r
fig, ax = plt.subplots(figsize=({width}, {height}))
"""
PYTHON_HEATMAP = """\
image = ax.imshow(grid, cmap="RdBu_r", vmin=-1, vmax=1)
for (i, j), r in np.ndenumerate(grid):
    if not np.isnan(r):
        ax.text(j, i, f"{r:.2f}", ha="center", va="center", fontsize=8)
"""
PYTHON_DOTS = """\
rows, columns = np.nonzero(~np.isnan(grid))
values = grid[rows, columns]
image = ax.scatter(columns, rows, s=(np.abs(values) * 28) ** 2, c=values, cmap="RdBu_r",
                   vmin=-1, vmax=1)
ax.set_xlim(-0.5, len(names) - 1.5)
ax.set_ylim(len(names) - 1.5, -0.5)
ax.set_aspect("equal")
"""
PYTHON_CORRELATION_AXES = """\
ax.set_xticks(range(len(names) - 1), [labels[n] for n in names[:-1]], rotation=45, ha="right")
ax.set_yticks(range(len(names) - 1), [labels[n] for n in names[1:]])
for side in ax.spines.values():
    side.set_visible(False)
fig.colorbar(image, ax=ax, label={coefficient}, shrink=0.8)
"""

R_SCATTER = """\
labels <- c({labels})
colours <- c({colours})
points <- do.call(rbind, lapply(names(labels), function(x) {{
  data.frame(predictor = labels[[x]], x = d[[x]], y = d[[y]])
}}))
points <- points[complete.cases(points), ]
points$predictor <- factor(points$predictor, levels = labels)
figure <- ggplot(points, aes(x, y, colour = predictor)) +
  geom_point(alpha = 0.6) +
  geom_smooth(method = "lm", formula = y ~ x, se = FALSE) +
  scale_colour_manual(values = unname(colours), guide = "none") +
  facet_wrap(~ predictor, scales = "free_x") +
  labs(x = NULL, y = {y_label}) +
  theme_minimal()
"""
PYTHON_SCATTER = """\
labels = {{{labels}}}
colours = [{colours}]
fig, axes = plt.subplots(1, len(labels), figsize=({width}, {height}), sharey=True, squeeze=False)
for ax, (x, label), colour in zip(axes[0], labels.items(), colours):
    both = d[[x, y]].dropna()
    ax.scatter(both[x], both[y], color=colour, alpha=0.6, s=14)
    slope, intercept = np.polyfit(both[x], both[y], 1)
    ends = np.array([both[x].min(), both[x].max()])
    ax.plot(ends, intercept + slope * ends, color=colour, linewidth=2)
    ax.set_title(label, fontsize=10)
axes[0][0].set_ylabel({y_label})
"""

R_BOXES = """\
points <- data.frame(group = group, y = y)
figure <- ggplot(points, aes(group, y)) +
  geom_boxplot(outlier.shape = NA, width = 0.5, colour = "{colour}") +
  geom_jitter(width = 0.12, height = 0, alpha = 0.6, colour = "{colour}") +
  stat_summary(fun = mean, geom = "point", shape = 23, size = 3, fill = "white",
               colour = "{colour}") +
  labs(x = {group_label}, y = {outcome_label}) +
  theme_minimal()
"""
PYTHON_BOXES = """\
values = [data.loc[data["group"] == g, "y"] for g in levels]
places = range(1, len(levels) + 1)
fig, ax = plt.subplots(figsize=({width}, {height}))
line = dict(color="{colour}")
ax.boxplot(values, positions=places, widths=0.5, showfliers=False, showmeans=True,
           boxprops=line, whiskerprops=line, capprops=line, medianprops=line,
           meanprops=dict(marker="D", markerfacecolor="white", markeredgecolor="{colour}"))
jitter = np.random.default_rng(1)
for place, group in zip(places, values):
    ax.scatter(place + jitter.uniform(-0.12, 0.12, len(group)), group, color="{colour}",
               alpha=0.6, s=12)
ax.set_xticks(places, levels)
ax.set_xlabel({group_label})
ax.set_ylabel({outcome_label})
"""

R_PAIRED_LINES = """\
points <- data.frame(id = rep(seq_len(nrow(pair)), 2), side = rep(1:2, each = nrow(pair)),
                     y = c(pair$first, pair$second))
means <- data.frame(side = 1:2, y = c(mean(pair$first), mean(pair$second)))
figure <- ggplot(points, aes(side, y)) +
  geom_line(aes(group = id), colour = "grey60", alpha = 0.35, linewidth = 0.3) +
  geom_line(data = means, colour = "{colour}", linewidth = 1.2) +
  geom_point(data = means, shape = 21, size = 3, fill = "white", colour = "{colour}",
             stroke = 1.2) +
  scale_x_continuous(breaks = 1:2, labels = c({first_label}, {second_label}),
                     expand = expansion(add = 0.3)) +
  labs(x = NULL, y = NULL) +
  theme_minimal()
"""
PYTHON_PAIRED_LINES = """\
fig, ax = plt.subplots(figsize=({width}, {height}))
for a, b in zip(pair["first"], pair["second"]):
    ax.plot([1, 2], [a, b], color="0.6", alpha=0.35, linewidth=0.5)
means = [pair["first"].mean(), pair["second"].mean()]
ax.plot([1, 2], means, color="{colour}", linewidth=2.5)
ax.scatter([1, 2], means, s=50, color="white", edgecolor="{colour}", linewidth=2, zorder=3)
ax.set_xticks([1, 2], [{first_label}, {second_label}])
ax.set_xlim(0.7, 2.3)
"""
R_TRAJECTORIES = """\
points <- data.frame(id = d[[{person}]], wave = d[[{wave}]], time = d[[{time}]],
                     y = d[[{y}]], fixed = predict(fit, re.form = NA))
# The observed mean and the fixed effects' prediction, averaged within each wave.
means <- aggregate(cbind(time, y, fixed) ~ wave, data = points, FUN = mean)
means <- means[order(means$time), ]
figure <- ggplot(points, aes(time, y)) +
  geom_line(aes(group = id), colour = "grey60", alpha = 0.35, linewidth = 0.3) +
  geom_line(data = means, aes(y = fixed), colour = "{colour}", linewidth = 1.2) +
  geom_point(data = means, shape = 21, size = 3, fill = "white", colour = "{colour}",
             stroke = 1.2) +
  {x_scale}labs(x = {x_title}, y = {label}) +
  theme_minimal()
"""
PYTHON_TRAJECTORIES = """\
d["fixed"] = fit.predict(d)
# The observed mean and the fixed effects' prediction, averaged within each wave.
means = d.groupby({wave})[[{time}, {y}, "fixed"]].mean().sort_values({time})
fig, ax = plt.subplots(figsize=({width}, {height}))
for _, rows in d.sort_values({time}).groupby({person}):
    ax.plot(rows[{time}], rows[{y}], color="0.6", alpha=0.35, linewidth=0.5)
ax.plot(means[{time}], means["fixed"], color="{colour}", linewidth=2.5)
ax.scatter(means[{time}], means[{y}], s=50, color="white", edgecolor="{colour}", linewidth=2,
           zorder=3)
{x_ticks}ax.set_xlabel({x_title})
ax.set_ylabel({label})
"""


def text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def r_named(pairs: dict[str, str]) -> str:
    return ", ".join(f"{text(k)} = {text(v)}" for k, v in pairs.items())


def python_named(pairs: dict[str, str]) -> str:
    return ", ".join(f"{text(k)}: {text(v)}" for k, v in pairs.items())


def framed(what: str, name: str, r_body: str, python_body: str, width: float, height: float):
    file = text(name)
    size = dict(width=f"{width:g}", height=f"{height:g}", dpi=FIGURE_DPI, file=file)
    return (
        R_SETUP.format(what=what, file=name) + r_body + R_SAVE.format(**size),
        PYTHON_SETUP.format(what=what, file=name) + python_body + PYTHON_SAVE.format(**size),
    )


def correlation(labels: dict[str, str], coefficient: str, dots: bool) -> tuple[str, str]:
    # Reads the correlations table the statistics code before it leaves, one row per pair.
    side = max(4.0, 1.5 + 0.55 * len(labels))
    fields = dict(
        labels=r_named(labels),
        coefficient=text(coefficient),
        width=f"{side + 1.5:g}",
        height=f"{side:g}",
    )
    r = R_CORRELATION_CELLS.format(**fields) + (R_DOTS if dots else R_HEATMAP).format(**fields)
    python = (
        PYTHON_CORRELATION_CELLS.format(**fields | {"labels": python_named(labels)})
        + (PYTHON_DOTS if dots else PYTHON_HEATMAP)
        + PYTHON_CORRELATION_AXES.format(**fields)
    )
    what = "the correlations as " + ("dots sized by |r|" if dots else "a heatmap")
    return framed(what + ", lower triangle", "correlations.png", r, python, side + 1.5, side)


def regression(labels: dict[str, str], y_label: str) -> tuple[str, str]:
    # Reads y, the outcome's column, which the regression code sets.
    colours = [style.group_color(k) for k in range(len(labels))]
    width = min(12.0, 1.0 + 3.6 * len(labels))
    fields = dict(y_label=text(y_label), width=f"{width:g}", height="3.6")
    r = R_SCATTER.format(
        labels=r_named(labels), colours=", ".join(text(c) for c in colours), **fields
    )
    python = PYTHON_SCATTER.format(
        labels=python_named(labels), colours=", ".join(text(c) for c in colours), **fields
    )
    what = f"{y_label} against each predictor with its least-squares line"
    return framed(what, "regression.png", r, python, width, 3.6)


def groups(group_label: str, outcome_label: str, count: int) -> tuple[str, str]:
    # Reads group and y in R, data and levels in Python, which the comparison code sets.
    width = max(4.0, 1.5 + 1.2 * count)
    fields = dict(
        colour=style.group_color(0),
        group_label=text(group_label),
        outcome_label=text(outcome_label),
        width=f"{width:g}",
        height="4",
    )
    what = f"{outcome_label} by {group_label}, a box per group with each person and the mean"
    return framed(
        what,
        "group_comparison.png",
        R_BOXES.format(**fields),
        PYTHON_BOXES.format(**fields),
        width,
        4,
    )


def paired(first_label: str, second_label: str) -> tuple[str, str]:
    # Reads pair, which the paired comparison code sets, in both languages.
    fields = dict(
        colour=style.wave_color(0),
        first_label=text(first_label),
        second_label=text(second_label),
        width="5",
        height="4",
    )
    what = f"each person's line from {first_label} to {second_label}, and the means"
    return framed(
        what,
        "paired_comparison.png",
        R_PAIRED_LINES.format(**fields),
        PYTHON_PAIRED_LINES.format(**fields),
        5,
        4,
    )


def trajectories(
    columns: dict[str, str], label: str, x_title: str, by_wave: bool
) -> tuple[str, str]:
    # Reads d and fit after the model; columns name the person, wave, time and outcome columns.
    colour = style.wave_color(0)
    names = {k: text(v) for k, v in columns.items()}
    x_scale = (
        'scale_x_continuous(breaks = means$time, labels = paste("Wave", means$wave)) +\n  '
        if by_wave
        else ""
    )
    x_ticks = (
        f'ax.set_xticks(means[{names["time"]}], [f"Wave {{w}}" for w in means.index])\n'
        if by_wave
        else ""
    )
    fields = dict(colour=colour, label=text(label), x_title=text(x_title), **names)
    r = R_TRAJECTORIES.format(x_scale=x_scale, **fields)
    python = PYTHON_TRAJECTORIES.format(x_ticks=x_ticks, width="7", height="4.2", **fields)
    what = f"each person's {label} over time, the observed mean and the fixed effects"
    return framed(what, "multilevel.png", r, python, 7, 4.2)


R_OCCASION_MEANS = """\
means$group <- {group}
figure <- ggplot(means, aes({first}, mean, colour = group, group = group)) +
  geom_line(position = position_dodge(0.15)) +
  geom_pointrange(aes(ymin = low, ymax = high), position = position_dodge(0.15)) +
  labs(x = NULL, y = {label}, colour = NULL) +
  theme_minimal(){legend}
"""
PYTHON_OCCASION_MEANS = """\
names = {names}
group = {group}
fig, ax = plt.subplots(figsize=({width}, {height}))
for k, (name, rows) in enumerate(means.groupby(group, sort=False)):
    x = np.arange(len(rows)) + 0.08 * (k - (group.nunique() - 1) / 2)
    ax.errorbar(x, rows["mean"], yerr=[rows["mean"] - rows["low"], rows["high"] - rows["mean"]],
                marker="o", capsize=3, label=name)
ax.set_xticks(range(len(levels[{first_name}])), levels[{first_name}])
ax.set_ylabel({label})
if group.nunique() > 1:
    ax.legend(frameon=False)
"""


def occasion_means(first: str, others: list[tuple[str, str]], label: str) -> tuple[str, str]:
    # Reads means and, in Python, levels, which the occasions' code sets; others as (column, name).
    if others:
        r_group = (
            "paste("
            + ", ".join(f"paste0({text(name + ': ')}, means[[{text(c)}]])" for c, name in others)
            + ', sep = ", ")'
        )
        columns = ", ".join(text(c) for c, _ in others)
        joined = 'lambda r: ", ".join(f"{names[c]}: {v}" for c, v in r.items())'
        python_group = f"means[[{columns}]].apply({joined}, axis=1)"
        legend = ""
    else:
        r_group = text(label)
        python_group = f"pd.Series({text(label)}, index=means.index)"
        legend = ' +\n  theme(legend.position = "none")'
    fields = dict(label=text(label), width="6", height="4")
    r = R_OCCASION_MEANS.format(group=r_group, first=first, legend=legend, **fields)
    names = "{" + python_named(dict(others)) + "}"
    python = PYTHON_OCCASION_MEANS.format(
        names=names, group=python_group, first_name=text(first), **fields
    )
    what = f"the estimated marginal means of {label} with their 95% CIs"
    return framed(what, "multilevel.png", r, python, 6, 4)
