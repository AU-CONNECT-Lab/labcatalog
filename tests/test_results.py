from labcatalog.reports import results
from labcatalog.stats.analysis import Correlation, Fit
from labcatalog.stats.analysis_script import ANOVA, WELCH, Comparison, GroupStats
from labcatalog.stats.cfa import IMPROPER, ONE_FACTOR, SUBSCALES, CfaFit
from labcatalog.stats.invariance import InvarianceStep, InvarianceTest
from labcatalog.stats.multilevel import Fitted, Term, Variance


def matrix_of(n: int, pairs: dict[tuple[int, int], tuple[float, float]]) -> list[list[Correlation]]:
    found = [[Correlation(120) for _ in range(n)] for _ in range(n)]
    for (i, j), (r, p) in pairs.items():
        found[i][j] = found[j][i] = Correlation(120, r, p)
    return found


def test_a_small_table_is_told_pair_by_pair():
    matrix = matrix_of(2, {(1, 0): (-0.342, 0.0002)})
    text = results.correlation_text(["Mood", "Sleep"], matrix, spearman=False)
    assert text == "Sleep was negatively correlated with Mood, r(118) = -.34, p < .001."
    matrix = matrix_of(2, {(1, 0): (0.05, 0.587)})
    text = results.correlation_text(["Mood", "Sleep"], matrix, spearman=True)
    assert text == "Sleep was not significantly correlated with Mood, rs(118) = .05, p = .587."


def test_a_large_table_names_its_strongest_significant_pairs():
    labels = ["A", "B", "C", "D"]
    matrix = matrix_of(
        4,
        {
            (1, 0): (0.30, 0.001),
            (2, 0): (0.10, 0.27),
            (2, 1): (0.55, 0.0001),
            (3, 0): (0.02, 0.8),
            (3, 1): (0.04, 0.6),
            (3, 2): (0.06, 0.5),
        },
    )
    text = results.correlation_text(labels, matrix, spearman=False)
    assert text.startswith("Of the 6 correlations, 2 were significant at p < .05.")
    assert text.endswith(
        "They were between C and B (r(118) = .55, p < .001) and B and A (r(118) = .30, p = .001)."
    )


def test_regression_reports_each_predictor():
    fit = Fit(Correlation(100, 0.4, 0.00004), 0.512, 0.118, 1.0, 0.2)
    text = results.regression_text({"x": fit}, {"x": "Sleep"}, "Mood")
    assert (
        text
        == "Sleep significantly predicted Mood, b = 0.51, SE = 0.12, p < .001, R² = .16, n = 100."
    )


def test_comparison_names_the_test_the_means_and_the_effect():
    two = Comparison(
        WELCH,
        [GroupStats("boys", 60, 3.21, 0.8), GroupStats("girls", 58, 2.9, 0.7)],
        2.104,
        110.34,
        None,
        0.038,
        0.38,
        effect_low=0.02,
        effect_high=0.74,
    )
    assert results.comparison_text(two, "Mood") == (
        "Mood differed significantly between boys (M = 3.21, SD = 0.80) and girls "
        "(M = 2.90, SD = 0.70), Welch's t(110.3) = 2.10, p = .038, d = 0.38, 95% CI [0.02, 0.74]."
    )
    three = Comparison(
        ANOVA,
        [GroupStats(g, 40, 3.0, 1.0) for g in ("a", "b", "c")],
        0.5,
        2,
        117,
        0.61,
        0.008,
    )
    text = results.comparison_text(three, "Mood")
    assert text.startswith("Mood did not differ significantly among a (M = 3.00, SD = 1.00), b")
    assert text.endswith("F(2, 117) = 0.50, p = .610, η² = .01.")


LABELS = {"total": "Total score", "sad": "Sadness", "worry": "Worry"}
FIT = {
    "chisq": 31.24,
    "df": 24.0,
    "p": 0.146,
    "cfi": 0.984,
    "tli": 0.976,
    "rmsea": 0.041,
    "srmr": None,
}


def test_cfa_reports_fit_loadings_and_omega():
    one = CfaFit(
        "mood",
        "child_w1",
        ONE_FACTOR,
        {"total": ["a", "b", "c"]},
        412,
        FIT,
        {("total", "a"): 0.45, ("total", "b"): 0.82, ("total", "c"): 0.6},
        {"total": 0.84},
    )
    assert results.cfa_text([one], LABELS) == (
        "A one-factor model of Total score, fitted in lavaan with the WLSMV estimator and the "
        "items as ordered categories (N = 412), gave χ²(24) = 31.24, p = .146, CFI = .98, "
        "TLI = .98, RMSEA = .04. Standardized loadings ranged from .45 to .82. ω was .84."
    )
    two = CfaFit("mood", "child_w1", SUBSCALES, {"sad": [], "worry": []}, 412, problem=IMPROPER)
    assert results.cfa_text([two], LABELS).startswith(
        "A model with one factor for each subscale (Sadness and Worry) could not be used: improper"
    )


def test_invariance_reports_each_step_against_the_one_before():
    test = InvarianceTest(
        "s",
        "child",
        "mood",
        ONE_FACTOR,
        {"total": []},
        {"1": 100, "2": 98},
        [
            InvarianceStep("metric", {**FIT, "cfi": 0.981, "rmsea": 0.043}, 4.1, 8.0, 0.85),
            InvarianceStep("configural", FIT),
        ],
    )
    text = results.invariance_text(test, LABELS, "waves")
    assert text.startswith("Invariance of a one-factor model of Total score across waves")
    assert "The configural model gave χ²(24) = 31.24, CFI = .984, RMSEA = .041." in text
    assert text.endswith(
        "Adding equal loadings gave χ²(24) = 31.24, CFI = .981, RMSEA = .043; against the step "
        "before, Δχ²(8) = 4.10, p = .850, ΔCFI = -.003, ΔRMSEA = .002."
    )


def test_multilevel_reports_the_design_icc_and_effects():
    fitted = Fitted(
        "Python",
        [("Person", 0.692)],
        [
            Term("Intercept", 3.0, 0.27, None, 11.1, 0.0001, 2.5, 3.6),
            Term("Time", -0.048, 0.029, 150.24, -1.63, 0.103, -0.105, 0.0096),
        ],
        [
            Variance("Person", "Intercept", 0.53, 0.73, None),
            Variance("Person", "Time", 0.06, 0.25, -0.293),
            Variance("Residual", "", 0.14, 0.37, None),
        ],
        484,
        189,
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
    assert results.multilevel_text(fitted, "Stress") == (
        "A multilevel model of Stress, fitted by REML in statsmodels, used 484 observations from "
        "189 people. In the model with only the random intercepts, the ICC was .69 at the person "
        "level. Fixed effects: Time, b = -0.05, SE = 0.03, t(150.2) = -1.63, p = .103, 95% CI "
        "[-0.10, 0.01]. Random effects: SD = 0.73 for the person intercepts, SD = 0.25 for the "
        "person slopes of Time (r = -.29 with the intercepts), and SD = 0.37 for the residuals."
    )
