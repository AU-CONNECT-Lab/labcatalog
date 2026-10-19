from collections.abc import Callable

from labcatalog.reports import results
from labcatalog.reports.templates import Wording
from labcatalog.stats.agreement import ICC, Agreement, IccRow
from labcatalog.stats.analysis import Correlation, Fit
from labcatalog.stats.analysis_script import WELCH, Comparison, GroupStats, MissingData, Variable
from labcatalog.stats.cfa import SUBSCALES, CfaFit
from labcatalog.stats.invariance import InvarianceStep, InvarianceTest
from labcatalog.stats.mediation import Effect, MediationFit, MediationModel
from labcatalog.stats.multilevel import Fitted, Term, Variance
from labcatalog.stats.panel import EQUAL, RICLPM, PanelFit, PanelModel, PanelPath

# Made-up results, one per analysis, that the Templates page writes with the wording being edited.
LABELS = ["Sleep problems", "Mood", "Stress", "Screen time"]
FIT = {
    "chisq": 31.2,
    "df": 19.0,
    "p": 0.038,
    "pvalue": 0.038,
    "cfi": 0.981,
    "tli": 0.972,
    "rmsea": 0.048,
    "rmsea_low": 0.012,
    "rmsea_high": 0.079,
    "srmr": 0.041,
}


def correlation(wording: Wording) -> str:
    values = {(1, 0): (0.32, 0.0004), (2, 0): (0.41, 0.0001), (2, 1): (-0.08, 0.38)}
    values |= {(3, 0): (0.21, 0.022), (3, 1): (-0.18, 0.049), (3, 2): (0.05, 0.59)}
    matrix = [[Correlation(120) for _ in LABELS] for _ in LABELS]
    for (i, j), (r, p) in values.items():
        matrix[i][j] = matrix[j][i] = Correlation(120, r, p)
    return results.correlation_text(LABELS, ["s", "m", "t", "v"], matrix, False, 2, wording)


def regression(wording: Wording) -> str:
    fits = {
        "s": Fit(Correlation(120, 0.32, 0.0004), 0.41, 0.11, 1.2, 0.3),
        "v": Fit(Correlation(120, 0.06, 0.51), 0.06, 0.09, 2.1, 0.2),
    }
    return results.regression_text(fits, {"s": LABELS[0], "v": LABELS[3]}, "Mood", 2, wording)


def missing(wording: Wording) -> str:
    found = MissingData(
        [("s", 118, 2), ("m", 105, 15), ("t", 112, 8)],
        [
            ((True, True, True), 97),
            ((True, False, True), 15),
            ((True, True, False), 6),
            ((False, True, True), 2),
        ],
    )
    return results.missing_text(found, LABELS[:3], wording)


def groups(wording: Wording) -> str:
    found = Comparison(
        WELCH,
        [GroupStats("Girls", 60, 3.2, 0.9), GroupStats("Boys", 58, 2.8, 1.0)],
        2.3,
        117.6,
        None,
        0.023,
        0.42,
        effect_low=0.06,
        effect_high=0.78,
    )
    return results.comparison_text(found, "Mood", 2, wording)


def agreement(wording: Wording) -> str:
    found = Agreement(
        ICC,
        2,
        n=60,
        icc=[
            IccRow("ICC2", 0.81, 0.70, 0.88, 9.5, 59, 59, 0.0),
            IccRow("ICC2k", 0.89, 0.82, 0.94, 9.5, 59, 59, 0.0),
        ],
    )
    return results.agreement_text(found, 2, None, wording)


def cfa(wording: Wording) -> str:
    found = CfaFit(
        "mood",
        "child_w1",
        SUBSCALES,
        {"sad": ["a", "b", "c"], "worry": ["d", "e", "f"]},
        214,
        FIT,
        {("sad", "a"): 0.52, ("sad", "b"): 0.84, ("worry", "d"): 0.61, ("worry", "e"): 0.77},
        {"sad": 0.81, "worry": 0.77},
    )
    return results.cfa_text([found], {"sad": "Sadness", "worry": "Worry"}, 2, wording)


def invariance(wording: Wording) -> str:
    found = InvarianceTest(
        "study",
        "child",
        "mood",
        SUBSCALES,
        {"sad": [], "worry": []},
        {"1": 214, "2": 198},
        [
            InvarianceStep("configural", {**FIT, "chisq": 52.4, "df": 38.0}),
            InvarianceStep(
                "metric", {**FIT, "chisq": 59.5, "df": 44.0, "cfi": 0.979}, 7.1, 6.0, 0.312
            ),
        ],
    )
    return results.invariance_text(
        found, {"sad": "Sadness", "worry": "Worry"}, "waves", "", wording
    )


def multilevel(wording: Wording) -> str:
    found = Fitted(
        "R",
        [("Person", 0.42)],
        [
            Term("Intercept", 3.1, 0.08, 178.0, 38.8, 0.0001, 2.94, 3.26),
            Term("Wave", -0.12, 0.04, 118.2, -3.0, 0.003, -0.2, -0.04),
        ],
        [
            Variance("Person", "Intercept", 0.37, 0.61, None),
            Variance("Residual", "", 0.23, 0.48, None),
        ],
        512,
        180,
        None,
        0,
        0,
        1.0,
        -0.5,
        None,
        None,
        False,
        [],
    )
    return results.multilevel_text(found, "Mood", 2, wording)


def panel(wording: Wording) -> str:
    model = PanelModel(LABELS[0], LABELS[1], ["1", "2", "3"], [], [])
    paths = [
        PanelPath(EQUAL, f"w{to}{wave}", "~", f"w{by}{wave - 1}", b, 0.05, p, None, None, beta)
        for to, by, b, p, beta in (("y", "x", 0.14, 0.006, 0.13), ("x", "y", 0.03, 0.41, 0.03))
        for wave in (2, 3)
    ]
    paths.append(PanelPath(RICLPM, "RIx", "~~", "RIy", 0.2, 0.05, 0.0001, None, None, 0.52))
    fit = PanelFit(
        180,
        {RICLPM: {**FIT, "chisq": 0.8, "df": 1.0, "pvalue": 0.371}},
        paths,
        {"equal": (1.9, 2.0, 0.387), "intercepts": (48.2, 3.0, 0.0001)},
    )
    return results.panel_text(model, fit, 2, wording)


def mediation(wording: Wording) -> str:
    def variable(label: str) -> Variable:
        return Variable(label, label, "child_w1", "score", label)

    model = MediationModel(variable(LABELS[2]), variable(LABELS[0]), variable(LABELS[1]))
    fit = MediationFit(
        180,
        {
            "a": Effect("a", 0.38, 0.09, 0.0001, 0.21, 0.55),
            "b": Effect("b", 0.29, 0.09, 0.001, 0.12, 0.46),
            "c": Effect("c", 0.21, 0.09, 0.02, 0.03, 0.39),
            "indirect": Effect("indirect", 0.11, 0.04, 0.004, 0.04, 0.2),
            "total": Effect("total", 0.32, 0.09, 0.0004, 0.15, 0.49),
        },
        {"df": 0.0},
    )
    return results.mediation_text(model, fit, 2, wording)


EXAMPLES: dict[str, Callable[[Wording], str]] = {
    "correlation": correlation,
    "regression": regression,
    "missing": missing,
    "groups": groups,
    "agreement": agreement,
    "cfa": cfa,
    "invariance": invariance,
    "multilevel": multilevel,
    "panel": panel,
    "mediation": mediation,
}
