from labcatalog.stats.analysis import Correlation, Fit
from labcatalog.stats.analysis_script import ANOVA, STUDENT, WELCH, Comparison, GroupStats
from labcatalog.stats.cfa import SUBSCALES, WLSMV, CfaFit
from labcatalog.stats.cfa import R as LAVAAN
from labcatalog.stats.invariance import STEPS, InvarianceStep, InvarianceTest

SIGNIFICANT = 0.05
# A table with this many pairs or fewer is told pair by pair; a larger one by its strongest pairs.
EVERY_PAIR = 3
STRONGEST = 5
TEST_SYMBOLS = {WELCH: "Welch's t", STUDENT: "t", ANOVA: "F"}
FIT_INDICES = {"cfi": "CFI", "tli": "TLI", "rmsea": "RMSEA", "srmr": "SRMR"}
# Invariance steps and changes in fit are read to the third decimal, as in their table.
FINE = 3
STEP_PHRASES = {
    "thresholds": "Holding the thresholds equal",
    "metric": "Adding equal loadings",
    "scalar": "Adding equal intercepts",
}


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


def cfa_text(fits: list[CfaFit], labels: dict[str, str], digits: int = 2) -> str:
    return " ".join(cfa_sentences(fit, labels, digits) for fit in fits)


def cfa_sentences(fit: CfaFit, labels: dict[str, str], digits: int) -> str:
    model = model_phrase(fit.kind, [labels[s] for s in fit.factors])
    if fit.problem:
        return f"{model.capitalize()} could not be used: {fit.problem}."
    package = "lavaan" if fit.engine == LAVAAN else "semopy"
    how = (
        "the WLSMV estimator and the items as ordered categories"
        if fit.estimator == WLSMV
        else "maximum likelihood and the items as continuous"
    )
    opening = f"{model.capitalize()}, fitted in {package} with {how} (N = {fit.n}),"
    if fit.fit.get("df") == 0:
        sentences = [f"{opening} fits exactly with three items, so it has no fit indices."]
    else:
        sentences = [f"{opening} gave {fit_indices(fit.fit, digits)}."]
    if fit.loadings:
        low, high = min(fit.loadings.values()), max(fit.loadings.values())
        sentences.append(
            f"Standardized loadings ranged from {bounded(low, digits)} to {bounded(high, digits)}."
        )
    omega = [(labels[s], v) for s, v in fit.omega.items()]
    if len(omega) == 1:
        sentences.append(f"ω was {bounded(omega[0][1], digits)}.")
    elif omega:
        sentences.append(
            f"ω was {series([f'{bounded(v, digits)} for {name}' for name, v in omega])}."
        )
    return " ".join(sentences)


def model_phrase(kind: str, names: list[str]) -> str:
    if kind == SUBSCALES:
        return f"a model with one factor for each subscale ({series(names)})"
    return f"a one-factor model of {series(names)}"


def fit_indices(values: dict[str, float | None], digits: int) -> str:
    parts = [f"χ²({values['df']:g}) = {number(values['chisq'], digits)}", p_text(values["p"])]
    parts += [
        f"{name} = {bounded(values[key], digits)}"
        for key, name in FIT_INDICES.items()
        if values.get(key) is not None
    ]
    return ", ".join(parts)


def invariance_text(
    test: InvarianceTest, labels: dict[str, str], across: str, freed: str = ""
) -> str:
    # across names the occasions, such as "waves" or "the answers to Child gender".
    model = model_phrase(test.kind, [labels[s] for s in test.factors])
    if test.problem:
        return f"Invariance of {model} across {across} could not be tested: {test.problem}."
    sentences = [
        f"Invariance of {model} across {across} was tested in steps, each holding one more set "
        "of parameters equal."
    ]
    if freed:
        sentences.append(f"Freed parameters: {freed}.")
    previous = None
    for step in sorted(test.steps, key=lambda s: STEPS.index(s.step)):
        before = previous.fit if previous and not previous.problem else {}
        sentences.append(step_sentence(step, before))
        previous = step
    return " ".join(sentences)


def step_sentence(step: InvarianceStep, before: dict[str, float | None]) -> str:
    name = STEP_PHRASES.get(step.step, "The configural model")
    if step.problem:
        return f"{name} gave no usable model: {step.problem}."
    values = step.fit
    found = [f"χ²({values['df']:g}) = {number(values['chisq'], 2)}"] + [
        f"{FIT_INDICES[key]} = {bounded(values[key], FINE)}"
        for key in ("cfi", "rmsea", "srmr")
        if values.get(key) is not None
    ]
    if step.chisq_diff is None:
        return f"{name} gave {', '.join(found)}."
    change = [
        f"Δχ²({step.df_diff:g}) = {number(step.chisq_diff, 2)}",
        p_text(step.p_diff),
        *[
            f"Δ{FIT_INDICES[key]} = {bounded(values[key] - before[key], FINE)}"
            for key in ("cfi", "rmsea")
            if values.get(key) is not None and before.get(key) is not None
        ],
    ]
    return f"{name} gave {', '.join(found)}; against the step before, {', '.join(change)}."
