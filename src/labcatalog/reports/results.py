from labcatalog.stats.analysis import Correlation, Fit
from labcatalog.stats.analysis_script import ANOVA, STUDENT, WELCH, Comparison, GroupStats

SIGNIFICANT = 0.05
# A table with this many pairs or fewer is told pair by pair; a larger one by its strongest pairs.
EVERY_PAIR = 3
STRONGEST = 5
TEST_SYMBOLS = {WELCH: "Welch's t", STUDENT: "t", ANOVA: "F"}


def correlation_text(
    labels: list[str], matrix: list[list[Correlation]], spearman: bool, digits: int = 2
) -> str:
    symbol = "rs" if spearman else "r"
    pairs = [
        (labels[i], labels[j], matrix[i][j])
        for i in range(len(labels))
        for j in range(i)
        if matrix[i][j].r is not None
    ]
    if len(pairs) <= EVERY_PAIR:
        return " ".join(pair_sentence(a, b, c, symbol, digits) for a, b, c in pairs)
    significant = sorted(
        (pair for pair in pairs if pair[2].p < SIGNIFICANT), key=lambda pair: -abs(pair[2].r)
    )
    verb = "was" if len(significant) == 1 else "were"
    opening = f"Of the {len(pairs)} correlations, {len(significant)} {verb} significant at p < .05."
    if not significant:
        return opening
    lead = (
        f"The {len(significant[:STRONGEST])} strongest were between"
        if len(significant) > STRONGEST
        else "They were between"
        if len(significant) > 1
        else "It was between"
    )
    shown = [f"{a} and {b} ({statistic(symbol, c, digits)})" for a, b, c in significant[:STRONGEST]]
    return f"{opening} {lead} {series(shown)}."


def pair_sentence(a: str, b: str, c: Correlation, symbol: str, digits: int) -> str:
    if c.p >= SIGNIFICANT:
        return f"{a} was not significantly correlated with {b}, {statistic(symbol, c, digits)}."
    direction = "positively" if c.r > 0 else "negatively"
    return f"{a} was {direction} correlated with {b}, {statistic(symbol, c, digits)}."


def statistic(symbol: str, c: Correlation, digits: int) -> str:
    return f"{symbol}({c.n - 2}) = {bounded(c.r, digits)}, {p_text(c.p)}"


def regression_text(
    fits: dict[str, Fit], labels: dict[str, str], outcome: str, digits: int = 2
) -> str:
    sentences = (
        ["Each predictor was entered in its own simple regression."] if len(fits) > 1 else []
    )
    for x, fit in fits.items():
        c = fit.correlation
        verb = "significantly predicted" if c.p < SIGNIFICANT else "did not significantly predict"
        sentences.append(
            f"{labels[x]} {verb} {outcome}, b = {number(fit.slope, digits)}, "
            f"SE = {number(fit.slope_se, digits)}, {p_text(c.p)}, "
            f"R² = {bounded(c.r**2, digits)}, n = {c.n}."
        )
    return " ".join(sentences)


def comparison_text(comparison: Comparison, outcome: str, digits: int = 2) -> str:
    groups = series([described(g, digits) for g in comparison.groups])
    significant = comparison.p < SIGNIFICANT
    test = f"{TEST_SYMBOLS[comparison.test]}({df_text(comparison)}) = {number(comparison.statistic, digits)}"
    if comparison.test == ANOVA:
        verb = (
            "differed significantly among" if significant else "did not differ significantly among"
        )
        effect = interval(
            "η²", comparison.effect, comparison.effect_low, comparison.effect_high, digits, bounded
        )
    else:
        verb = (
            "differed significantly between"
            if significant
            else "did not differ significantly between"
        )
        effect = interval(
            "d", comparison.effect, comparison.effect_low, comparison.effect_high, digits, number
        )
    return f"{outcome} {verb} {groups}, {test}, {p_text(comparison.p)}, {effect}."


def df_text(comparison: Comparison) -> str:
    # Welch's df is fractional; Student's and the ANOVA's are whole.
    if comparison.test == WELCH:
        return f"{comparison.df1:.1f}"
    if comparison.test == STUDENT:
        return f"{comparison.df1:g}"
    return f"{comparison.df1:g}, {comparison.df2:g}"


def described(group: GroupStats, digits: int) -> str:
    if group.mean is None:
        return group.label
    sd = "" if group.sd is None else f", SD = {number(group.sd, digits)}"
    return f"{group.label} (M = {number(group.mean, digits)}{sd})"


def interval(
    name: str, value: float, low: float | None, high: float | None, digits: int, shown
) -> str:
    text = f"{name} = {shown(value, digits)}"
    if low is None or high is None:
        return text
    return f"{text}, 95% CI [{shown(low, digits)}, {shown(high, digits)}]"


def number(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def bounded(value: float, digits: int) -> str:
    # Values that cannot exceed 1 drop the leading zero.
    return number(value, digits).replace("0.", ".", 1)


def p_text(p: float) -> str:
    return "p < .001" if p < 0.001 else f"p = {p:.3f}".replace("0.", ".", 1)


def series(parts: list[str]) -> str:
    if len(parts) < 3:
        return " and ".join(parts)
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"
