from labcatalog.stats.agreement import ICC, Agreement
from labcatalog.stats.analysis import Correlation, Fit
from labcatalog.stats.analysis_script import (
    ANOVA,
    STUDENT,
    WELCH,
    Comparison,
    GroupStats,
    MissingData,
)
from labcatalog.stats.cfa import (
    GENERAL_KINDS,
    MEASUREMENT,
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
from labcatalog.stats.mediation import (
    Effect,
    MediationFit,
    MediationModel,
    at_labels,
    conditions,
    index_label,
    indexed,
    intervals_text,
    method_text,
)
from labcatalog.stats.multilevel import RESIDUAL, Fitted, Term, Variance
from labcatalog.stats.multilevel import R as LME4
from labcatalog.stats.panel import EQUAL, RICLPM, PanelFit, PanelModel

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


def missing_text(missing: MissingData, labels: list[str]) -> str:
    people, k = missing.people, len(labels)
    if not people:
        return ""
    things = "variable" if k == 1 else f"{k} variables"
    complete = missing.complete
    if complete == people:
        return f"All {people} people had values on the {things}."
    opening = (
        f"Of the {people} people, {complete} ({percent(complete, people)}) had values on "
        f"{'the variable' if k == 1 else f'all {k} variables'}."
    )
    if k == 1:
        return opening
    shares = sorted(zip(labels, missing.counts, strict=True), key=lambda x: x[1][2])
    (low_label, low), (high_label, high) = shares[0], shares[-1]
    if low[2] == high[2]:
        return f"{opening} Each variable was missing for {high[2]} ({percent(high[2], people)})."
    return (
        f"{opening} Missing values ranged from {low[2]} ({percent(low[2], people)}) for "
        f"{low_label} to {high[2]} ({percent(high[2], people)}) for {high_label}."
    )


def agreement_text(agreement: Agreement, digits: int = 2) -> str:
    k = agreement.raters
    among = "between the two raters" if k == 2 else f"among the {k} raters"
    if agreement.kind == ICC:
        rows = {r.type: r for r in agreement.icc}
        single, mean = rows["ICC2"], rows["ICC2k"]
        whom = "both" if k == 2 else "all of them"
        return (
            f"Agreement {among}, on the {agreement.n} people {whom} rated, was "
            f"{interval('ICC(2,1)', single.icc, single.low, single.high, digits, bounded)} "
            "(two-way random effects, absolute agreement, single rater); for the mean of the "
            f"raters, {interval('ICC(2,k)', mean.icc, mean.low, mean.high, digits, bounded)}."
        )
    pairs = agreement.kappas
    if k == 2:
        [pair] = pairs
        if pair.kappa is None:
            return ""
        plain = interval("κ", pair.kappa, pair.kappa_low, pair.kappa_high, digits, bounded)
        text = f"Agreement {among}, on the {pair.n} people both rated, was Cohen's {plain}"
        if pair.weighted is None:
            return f"{text}."
        weighted = interval(
            "κ", pair.weighted, pair.weighted_low, pair.weighted_high, digits, bounded
        )
        return f"{text}; with quadratic weights, {weighted}."
    values = [p.kappa for p in pairs if p.kappa is not None]
    if agreement.light is None:
        return ""
    return (
        f"Cohen's κ averaged over the {len(pairs)} pairs of the {k} raters (Light's κ) was "
        f"{bounded(agreement.light, digits)}, ranging from {bounded(min(values), digits)} to "
        f"{bounded(max(values), digits)} across pairs."
    )


def panel_text(model: PanelModel, fit: PanelFit, digits: int = 2) -> str:
    x, y, t = model.x_label, model.y_label, len(model.waves)
    values = {**fit.fits[RICLPM]}
    values["p"] = values["pvalue"]
    sentences = [
        f"A random intercept cross-lagged panel model (RI-CLPM) of {x} and {y} over {t} waves "
        f"(N = {fit.n}) gave {fit_indices(values, digits)}."
    ]
    chisq, df, p = fit.tests["equal"]
    change = f"Δχ²({df:g}) = {number(chisq, digits)}, {p_text(p)}"
    if fit.equal_holds:
        sentences.append(
            f"Holding the lagged paths equal across waves did not worsen fit, {change}, so the "
            "lagged paths are reported from that model."
        )
    else:
        sentences.append(
            f"Holding the lagged paths equal across waves worsened fit, {change}, so the lagged "
            "paths are reported as estimated at each wave."
        )
    chisq, df, p = fit.tests["intercepts"]
    verb = "improved" if p < SIGNIFICANT else "did not improve"
    sentences.append(
        f"The random intercepts {verb} fit over the cross-lagged panel model without them, "
        f"Δχ²({df:g}) = {number(chisq, digits)}, {p_text(p)}."
    )
    between = fit.correlation(RICLPM, "RIx", "RIy")
    if between is not None and between.standardized is not None:
        sentences.append(
            "The random intercepts, the stable differences between people, correlated "
            f"r = {bounded(between.standardized, digits)}, {p_text(between.p)}."
        )
    chosen = EQUAL if fit.equal_holds else RICLPM
    for kind, phrase in (("x_to_y", f"{x} predicted {y}"), ("y_to_x", f"{y} predicted {x}")):
        paths = fit.lagged(chosen, kind)
        if not paths:
            continue
        if chosen == EQUAL:
            path = paths[0]
            ordered = sorted(q.standardized for q in paths if q.standardized is not None)
            betas = list(dict.fromkeys(bounded(b, digits) for b in ordered))
            if len(betas) > 1:
                spread = f" (β from {betas[0]} to {betas[-1]})"
            else:
                spread = f" (β = {betas[0]})" if betas else ""
            sentences.append(
                f"Within people, {phrase} at the next wave, b = {number(path.estimate, digits)}"
                f"{spread}, {p_text(path.p)}."
            )
        else:
            steps = [
                f"from wave {model.waves[q.wave - 2]} to {model.waves[q.wave - 1]}, β = "
                f"{bounded(q.standardized, digits)}, {p_text(q.p)}"
                for q in paths
                if q.standardized is not None
            ]
            sentences.append(f"Within people, {phrase} at the next wave {series(steps)}.")
    return " ".join(sentences)


def percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%"


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
    if fit.kind == MEASUREMENT and fit.correlations:
        values = [c["r"] for c in fit.correlations.values()]
        low, high = min(values), max(values)
        sentences.append(
            f"The factors correlated {bounded(values[0], digits)}."
            if len(values) == 1
            else f"Factor correlations ranged from {bounded(low, digits)} to "
            f"{bounded(high, digits)}."
        )
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
    if kind == MEASUREMENT:
        return f"a measurement model with a correlated factor for each of {series(names)}"
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
    ws = [moderator.variable.label for moderator in model.moderators]
    how = method_text(fit)
    # Asides about the model, each set off by commas.
    asides = []
    if ws:
        asides.append(f"with {series(ws)} as moderator{'s' if len(ws) > 1 else ''}")
    if model.items:
        asides.append(factors(model))
    moderator = "".join(f", {a}" for a in asides) + ("," if asides else "")
    sentences = [
        f"A mediation model of {x} on {y} through {m}{moderator} was fitted in "
        f"{fit.package} with "
        f"{how} (N = {fit.n})."
    ]

    means = " at the mean of the moderator" if len(ws) == 1 else " at the means of the moderators"

    def path(key: str, symbol: str) -> str:
        return f"{symbol} = {estimate(e[key], digits)}{means if key in moderated else ''}"

    sentences.append(
        f"The path from {x} to {m} was {path('a', 'a')}, and the path from {m} to {y}, with {x} "
        f"held constant, was {path('b', 'b')}."
    )
    named = list(zip(model.tags, ws, strict=True))
    names = {f"a_xw{s}": f"{x} × {w} on {m}" for s, w in named}
    names |= {f"b_mw{s}": f"{m} × {w} on {y}" for s, w in named}
    names |= {f"c_xw{s}": f"{x} × {w} on {y}" for s, w in named}
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
    places = [
        at_labels(moderator.variable, values)
        for moderator, values in zip(model.moderators, fit.at, strict=True)
    ]
    for kind in ("indirect", "direct"):
        found = conditions(model, fit, kind)
        if found and all(label in e for label, _ in found):
            # One moderator says where; with two, each is named with its value.
            parts = [
                f"{estimate(e[label], digits)} at {places[spots[0][0]][spots[0][1] - 1]}"
                if len(ws) == 1
                else f"{estimate(e[label], digits)} with "
                + " and ".join(f"{ws[k]} at {places[k][i - 1]}" for k, i in spots)
                for label, spots in found
            ]
            sentences.append(f"The conditional {kind} effect was {series(parts)}.")
    for k in indexed(model):
        label = index_label(model, k)
        if label in e:
            what = (
                "moderated mediation" if len(ws) == 1 else f"partial moderated mediation by {ws[k]}"
            )
            sentences.append(f"The index of {what} was {estimate(e[label], digits)}.")
    sentences.append(f"Confidence intervals are {intervals_text(fit)}.")
    if fit.fit.get("df"):
        sentences.append(
            f"The model gave {fit_indices({**fit.fit, 'p': fit.fit['pvalue']}, digits)}."
        )
    return " ".join(sentences)


def factors(model: MediationModel) -> str:
    return "with each score as a factor of its items"


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
