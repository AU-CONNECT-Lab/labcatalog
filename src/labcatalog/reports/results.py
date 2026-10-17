from labcatalog.stats.analysis import Correlation, Fit
from labcatalog.stats.analysis_script import ANOVA, STUDENT, WELCH, Comparison, GroupStats
from labcatalog.stats.cfa import (
    GENERAL_KINDS,
    MIN_SUBSCALES,
    MLR,
    SECOND_ORDER,
    SUBSCALE_SCORES,
    SUBSCALES,
    WLSMV,
    CfaFit,
    scores_of,
)
from labcatalog.stats.cfa import R as LAVAAN
from labcatalog.stats.invariance import STEPS, InvarianceStep, InvarianceTest
from labcatalog.stats.mediation import Effect, MediationFit, MediationModel, at_labels
from labcatalog.stats.multilevel import RESIDUAL, Fitted, Term, Variance
from labcatalog.stats.multilevel import R as LME4

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
    labels: list[str],
    instruments: list[str],
    matrix: list[list[Correlation]],
    spearman: bool,
    digits: int = 2,
) -> str:
    symbol = "rs" if spearman else "r"
    pairs = [
        (labels[i], labels[j], matrix[i][j], instruments[i] == instruments[j])
        for i in range(len(labels))
        for j in range(i)
        if matrix[i][j].r is not None
    ]
    if len(pairs) <= EVERY_PAIR:
        return " ".join(pair_sentence(a, b, c, symbol, digits) for a, b, c, _ in pairs)
    significant = [pair for pair in pairs if pair[2].p < SIGNIFICANT]
    verb = "was" if len(significant) == 1 else "were"
    opening = f"Of the {len(pairs)} correlations, {len(significant)} {verb} significant at p < .05."
    if not significant:
        return opening
    # Scores of one instrument share items, so their correlations say little and are left out.
    between = sorted((p for p in significant if not p[3]), key=lambda p: -abs(p[2].r))
    if not between:
        return f"{opening} All of them were between scores of the same instrument."
    lead = (
        f"Between instruments, the {STRONGEST} strongest were between"
        if len(between) > STRONGEST
        else "Between instruments, they were between"
        if len(between) > 1
        else "Between instruments, it was between"
    )
    shown = [f"{a} and {b} ({statistic(symbol, c, digits)})" for a, b, c, _ in between[:STRONGEST]]
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
    model = model_phrase(fit.kind, [labels[s] for s in scores_of(fit)])
    if fit.problem:
        return f"{opening_case(model)} could not be used: {fit.problem}."
    package = "lavaan" if fit.engine == LAVAAN else "semopy"
    indicators = "subscale scores" if fit.kind == SUBSCALE_SCORES else "items"
    how = (
        f"the WLSMV estimator and the {indicators} as ordered categories"
        if fit.estimator == WLSMV
        else f"robust maximum likelihood (MLR) and the {indicators} as continuous"
        if fit.estimator == MLR
        else f"maximum likelihood and the {indicators} as continuous"
    )
    opening = f"{opening_case(model)}, fitted in {package} with {how} (N = {fit.n}),"
    if fit.fit.get("df") == 0:
        sentences = [f"{opening} fits exactly with three {indicators}, so it has no fit indices."]
    else:
        sentences = [f"{opening} gave {fit_indices(fit.fit, digits)}."]
    if fit.kind == SECOND_ORDER and len(fit.factors) == MIN_SUBSCALES:
        sentences.append("With three subscales, its fit equals that of the subscale model.")
    if fit.loadings:
        low, high = min(fit.loadings.values()), max(fit.loadings.values())
        which = " of the subscales on the general factor" if fit.kind in GENERAL_KINDS else ""
        sentences.append(
            f"Standardized loadings{which} ranged from {bounded(low, digits)} to "
            f"{bounded(high, digits)}."
        )
    if fit.general_omega is not None:
        name = "Hierarchical ω" if fit.kind == SECOND_ORDER else "ω of the summed subscale scores"
        sentences.append(f"{name} was {bounded(fit.general_omega, digits)}.")
    omega = [(labels[s], v) for s, v in fit.omega.items()]
    if len(omega) == 1:
        sentences.append(f"ω was {bounded(omega[0][1], digits)}.")
    elif omega:
        sentences.append(
            f"ω was {series([f'{bounded(v, digits)} for {name}' for name, v in omega])}."
        )
    return " ".join(sentences)


def opening_case(text: str) -> str:
    # Only the first letter, so labels inside keep their own case.
    return text[:1].upper() + text[1:]


def model_phrase(kind: str, names: list[str]) -> str:
    if kind == SUBSCALES:
        return f"a model with one factor for each subscale ({series(names)})"
    if kind == SECOND_ORDER:
        return f"a second-order model with a general factor over the subscales ({series(names)})"
    if kind == SUBSCALE_SCORES:
        return f"a one-factor model of the subscale scores ({series(names)})"
    return f"a one-factor model of {series(names)}"


def fit_indices(values: dict[str, float | None], digits: int) -> str:
    parts = [f"χ²({values['df']:g}) = {number(values['chisq'], digits)}", p_text(values["p"])]
    parts += [
        f"{name} = {bounded(values[key], digits)}"
        for key, name in FIT_INDICES.items()
        if values.get(key) is not None
    ]
    if values.get("rmsea_low") is not None:
        low, high = bounded(values["rmsea_low"], digits), bounded(values["rmsea_high"], digits)
        rmsea = parts.index(f"RMSEA = {bounded(values['rmsea'], digits)}")
        parts.insert(rmsea + 1, f"90% CI [{low}, {high}]")
    return ", ".join(parts)


def mediation_text(model: MediationModel, fit: MediationFit, digits: int = 2) -> str:
    x, m, y = model.x.label, model.m.label, model.y.label
    e, moderated = fit.effects, model.moderated
    w = model.moderators[0].variable.label if model.moderators else ""
    how = (
        "robust maximum likelihood (MLR) for its fit and maximum likelihood for its estimates"
        if fit.estimator == MLR
        else "maximum likelihood"
    )
    moderator = f", with {w} as moderator" if w else ""
    sentences = [
        f"A mediation model of {x} on {y} through {m}{moderator} was fitted in lavaan with "
        f"{how} (N = {fit.n})."
    ]

    def path(key: str, symbol: str) -> str:
        where = " at the mean of the moderator" if key in moderated else ""
        return f"{symbol} = {estimate(e[key], digits)}{where}"

    sentences.append(
        f"The path from {x} to {m} was {path('a', 'a')}, and the path from {m} to {y}, with {x} "
        f"held constant, was {path('b', 'b')}."
    )
    names = {"a_xw": f"{x} × {w} on {m}", "b_mw": f"{m} × {w} on {y}", "c_xw": f"{x} × {w} on {y}"}
    parts = [f"{name}, {estimate(e[key], digits)}" for key, name in names.items() if key in e]
    if parts:
        word = "interaction was" if len(parts) == 1 else "interactions were"
        sentences.append(f"The {word} {series(parts)}.")
    direct = f"the direct effect was {path('c', 'c′')}"
    if "indirect" in e:
        total = f"; the total effect was c = {estimate(e['total'], digits)}" if "total" in e else ""
        sentences.append(
            f"The indirect effect through {m} was ab = {estimate(e['indirect'], digits)}, and "
            f"{direct}{total}."
        )
    else:
        sentences.append(f"{opening_case(direct)}.")
    places = at_labels(model, fit)
    for kind in ("indirect", "direct"):
        found = [e.get(f"{kind}_{k}") for k in range(1, len(places) + 1)]
        if places and all(found):
            parts = [
                f"{estimate(f, digits)} at {place}" for f, place in zip(found, places, strict=True)
            ]
            sentences.append(f"The conditional {kind} effect was {series(parts)}.")
    if "index" in e:
        sentences.append(f"The index of moderated mediation was {estimate(e['index'], digits)}.")
    resamples = (
        f"{fit.resamples} of {fit.bootstrap}" if fit.resamples < fit.bootstrap else fit.bootstrap
    )
    sentences.append(
        f"Confidence intervals are percentile bootstrap intervals from {resamples} resamples."
    )
    if fit.fit.get("df"):
        sentences.append(
            f"The model gave {fit_indices({**fit.fit, 'p': fit.fit['pvalue']}, digits)}."
        )
    return " ".join(sentences)


def estimate(effect: Effect, digits: int) -> str:
    if effect.low is None:
        return number(effect.estimate, digits)
    low, high = number(effect.low, digits), number(effect.high, digits)
    return f"{number(effect.estimate, digits)}, 95% CI [{low}, {high}]"


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


def multilevel_text(fitted: Fitted, outcome: str, digits: int = 2) -> str:
    package = "lme4" if fitted.engine == LME4 else "statsmodels"
    nested = f" in {fitted.groups} groups" if fitted.groups is not None else ""
    sentences = [
        f"A multilevel model of {outcome}, fitted by REML in {package}, used "
        f"{fitted.observations} observations from {fitted.people} people{nested}."
    ]
    if fitted.icc:
        found = [
            f"{bounded(icc, digits)} at the {level.lower()} level" for level, icc in fitted.icc
        ]
        sentences.append(
            f"In the model with only the random intercepts, the ICC was {series(found)}."
        )
    terms = [t for t in fitted.fixed if t.label != "Intercept"]
    if terms:
        sentences.append(f"Fixed effects: {'; '.join(term_text(t, digits) for t in terms)}.")
    if fitted.random:
        found = [variance_text(v, digits) for v in fitted.random]
        sentences.append(f"Random effects: {series(found)}.")
    if fitted.singular:
        sentences.append("The fit was singular, so some random effects are estimated as zero.")
    return " ".join(sentences)


def term_text(term: Term, digits: int) -> str:
    test = "z" if term.df is None else f"t({term.df:.1f})"
    return (
        f"{term.label}, b = {number(term.estimate, digits)}, SE = {number(term.se, digits)}, "
        f"{test} = {number(term.statistic, digits)}, {p_text(term.p)}, "
        f"95% CI [{number(term.low, digits)}, {number(term.high, digits)}]"
    )


def variance_text(variance: Variance, digits: int) -> str:
    sd = f"SD = {number(variance.sd, digits)}"
    if variance.level == RESIDUAL:
        return f"{sd} for the residuals"
    if variance.term == "Intercept":
        return f"{sd} for the {variance.level.lower()} intercepts"
    tied = (
        f" (r = {bounded(variance.correlation, digits)} with the intercepts)"
        if variance.correlation is not None
        else ""
    )
    return f"{sd} for the {variance.level.lower()} slopes of {variance.term}{tied}"
