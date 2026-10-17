from labcatalog.reports import results
from labcatalog.stats.analysis import Correlation, Fit
from labcatalog.stats.analysis_script import ANOVA, WELCH, Comparison, GroupStats


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
