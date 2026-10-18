# Each analysis also runs the way JASP calls it, in JASP's own R and packages.
import os
import shutil
import subprocess
from dataclasses import replace
from glob import glob
from pathlib import Path

import pandas as pd
import pytest

from labcatalog.data.scoring import score_items
from labcatalog.pipeline import run_catalog
from labcatalog.stats import analysis, attrition, cfa, group_invariance, invariance
from labcatalog.stats import analysis_script as script
from labcatalog.stats import multilevel as ml
from labcatalog.stats.rbridge import (
    ANALYSIS_PACKAGES,
    CFA_PACKAGES,
    MULTILEVEL_PACKAGES,
    r_status,
)

JASP = next(iter(sorted(glob("C:/Program Files*/JASP"))), None)
JASP_R = f"{JASP}/R/bin/Rscript.exe"
MODULES = f"{JASP}/Modules/module_libs"
EMS = "example_mood.ems_total@child_w1"
EPS = "example_parent_stress.eps_mean@parent_w1"
GENDER = "item:example_demographics.dem_gender@parent_w1"
EDUCATION = "item:example_demographics.dem_edu@parent_w1"

needs_jasp = pytest.mark.skipif(
    JASP is None or not Path(JASP_R).exists(), reason="JASP is not installed"
)
pytestmark = needs_jasp


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


def ready(packages) -> bool:
    return rscript() is not None and not r_status(rscript(), packages).missing


def engines(packages=ANALYSIS_PACKAGES) -> list[str | None]:
    # Ours in Python always, and in R when the user's R has the packages.
    return [None, rscript()] if ready(packages) else [None]


def in_jasp(tmp_path: Path, modules: list[str], code: str, data: pd.DataFrame) -> dict:
    # code reads d and leaves a named list `out` of numbers.
    data.to_csv(tmp_path / "jasp_data.csv", index=False)
    body = (
        f'd <- read.csv("{(tmp_path / "jasp_data.csv").as_posix()}", check.names = FALSE)\n'
        f"{code}\n"
        "write.csv(data.frame(name = names(out), value = unlist(out)), "
        f'"{(tmp_path / "jasp_out.csv").as_posix()}", row.names = FALSE)\n'
    )
    (tmp_path / "jasp.R").write_text(body, encoding="utf-8")
    env = os.environ | {
        "R_LIBS": ";".join(f"{MODULES}/{m}" for m in modules),
        # The user's own library is for their R, not JASP's.
        "R_LIBS_USER": str(tmp_path),
    }
    done = subprocess.run(
        [JASP_R, str(tmp_path / "jasp.R")], env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr[-2000:]
    found = pd.read_csv(tmp_path / "jasp_out.csv")
    return dict(zip(found["name"], found["value"], strict=True))


@pytest.fixture
def result(mock_project):
    return run_catalog(mock_project)


@pytest.fixture
def sample(result):
    return analysis.build_sample(result, ["parent_w1", "child_w1"], True)


@pytest.mark.parametrize("engine", engines())
def test_correlation_and_regression_match_jasp(result, sample, tmp_path, engine):
    data = script.AnalysisData(result, sample)
    x, y = data.score(EPS), data.score(EMS)
    frame = data.frame()
    found, _ = script.run_code(
        result, sample, frame, script.correlation_code([x, y], "pearson"), engine
    )
    _, matrix = script.read_correlations(found, [x.column, y.column])
    found, _ = script.run_code(result, sample, frame, script.regression_code([x], y), engine)
    fit = script.read_regressions(found, {x.column: EPS})[EPS]
    # jaspRegression: cor.test on pairwise complete cases, and lm.
    jasp = in_jasp(
        tmp_path,
        ["jaspRegression"],
        f"""
test <- cor.test(d[["{x.column}"]], d[["{y.column}"]])
fit <- summary(lm(d[["{y.column}"]] ~ d[["{x.column}"]]))
out <- list(r = test$estimate, p = test$p.value, low = test$conf.int[1],
            high = test$conf.int[2], slope = fit$coefficients[2, 1],
            slope_se = fit$coefficients[2, 2], intercept = fit$coefficients[1, 1],
            r2 = fit$r.squared)
""",
        frame,
    )
    assert (matrix[1][0].r, matrix[1][0].p) == pytest.approx((jasp["r"], jasp["p"]), rel=1e-6)
    assert (fit.correlation.low, fit.correlation.high) == pytest.approx(
        (jasp["low"], jasp["high"]), rel=1e-6
    )
    assert (fit.slope, fit.slope_se, fit.intercept) == pytest.approx(
        (jasp["slope"], jasp["slope_se"], jasp["intercept"]), rel=1e-6
    )
    assert fit.correlation.r**2 == pytest.approx(jasp["r2"], rel=1e-6)


def comparison(result, sample, group_key, t_test, engine):
    data = script.AnalysisData(result, sample)
    group, outcome = data.item(group_key), data.score(EMS)
    if t_test != script.ANOVA:
        group = replace(group, options=group.options[:2])
    frame = data.frame()
    plan = script.comparison_plan(frame, group, outcome, t_test)
    found, _ = script.run_code(result, sample, frame, plan.code, engine)
    return script.read_comparison(found, plan), frame, group, outcome


@pytest.mark.parametrize("engine", engines())
@pytest.mark.parametrize("t_test", [script.WELCH, script.STUDENT])
def test_t_tests_and_d_match_jasp(result, sample, tmp_path, t_test, engine):
    found, frame, group, outcome = comparison(result, sample, GENDER, t_test, engine)
    values = [value for value, _ in group.options]
    # jaspTTests: t.test; d over the pooled SD (Student) or the mean of the variances (Welch).
    jasp = in_jasp(
        tmp_path,
        ["jaspTTests"],
        f"""
a <- d[["{outcome.column}"]][d[["{group.column}"]] == {values[0]}]
b <- d[["{outcome.column}"]][d[["{group.column}"]] == {values[1]}]
a <- a[!is.na(a)]; b <- b[!is.na(b)]
test <- t.test(a, b, var.equal = {"TRUE" if t_test == script.STUDENT else "FALSE"})
na <- length(a); nb <- length(b)
pooled <- sqrt(((na - 1) * var(a) + (nb - 1) * var(b)) / (na + nb - 2))
spread <- {"pooled" if t_test == script.STUDENT else "sqrt((var(a) + var(b)) / 2)"}
out <- list(t = test$statistic, df = test$parameter, p = test$p.value,
            low = test$conf.int[1], high = test$conf.int[2], d = (mean(a) - mean(b)) / spread)
""",
        frame,
    )
    assert (found.statistic, found.df1, found.p) == pytest.approx(
        (jasp["t"], jasp["df"], jasp["p"]), rel=1e-6
    )
    assert (found.low, found.high) == pytest.approx((jasp["low"], jasp["high"]), rel=1e-6)
    assert found.effect == pytest.approx(jasp["d"], rel=1e-6)


@pytest.mark.parametrize("engine", engines())
def test_anova_and_its_effect_sizes_match_jasp(result, sample, tmp_path, engine):
    found, frame, group, outcome = comparison(result, sample, EDUCATION, script.ANOVA, engine)
    # jaspAnova: type III sums of squares; eta and omega squared from effectsize, two-sided.
    jasp = in_jasp(
        tmp_path,
        ["jaspAnova"],
        f"""
d <- d[!is.na(d[["{outcome.column}"]]) & !is.na(d[["{group.column}"]]), ]
d$g <- factor(d[["{group.column}"]])
d <- d[d$g %in% names(which(table(d$g) >= 2)), ]
d$g <- droplevels(d$g)
options(contrasts = c("contr.sum", "contr.poly"))
model <- aov(d[["{outcome.column}"]] ~ g, data = d)
table <- car::Anova(model, type = 3)
eta <- effectsize::eta_squared(model, partial = FALSE, alternative = "two.sided")
omega <- effectsize::omega_squared(model, partial = FALSE, alternative = "two.sided")
out <- list(f = table["g", "F value"], df1 = table["g", "Df"],
            df2 = table["Residuals", "Df"], p = table["g", "Pr(>F)"],
            eta = eta$Eta2[1], eta_low = eta$CI_low[1], eta_high = eta$CI_high[1],
            omega = omega$Omega2[1], omega_low = omega$CI_low[1], omega_high = omega$CI_high[1])
""",
        frame,
    )
    assert (found.statistic, found.df1, found.df2, found.p) == pytest.approx(
        (jasp["f"], jasp["df1"], jasp["df2"], jasp["p"]), rel=1e-6
    )
    assert found.effect == pytest.approx(jasp["eta"], rel=1e-6)
    # Only R gives omega squared.
    if engine is not None:
        assert found.omega == pytest.approx(jasp["omega"], rel=1e-5, abs=1e-8)
        # The interval's root search changed after JASP's effectsize 1.0.1; we use the user's R.
        assert (found.omega_low, found.omega_high) == pytest.approx(
            (jasp["omega_low"], jasp["omega_high"]), rel=1e-2, abs=1e-8
        )
        assert (found.effect_low, found.effect_high) == pytest.approx(
            (jasp["eta_low"], jasp["eta_high"]), rel=1e-5, abs=1e-8
        )


def test_alpha_matches_jasp(result, tmp_path):
    key = "example_mood.ems_total@child_w1"
    summary = next(s for s in result.summary.scores if s.key == key)
    score = next(s for s in result.catalog.scores if s.key == key)
    items = score_items(result.datasets["child_w1"], score)
    # jaspReliability: Bayesrel's alpha on the pairwise covariance matrix.
    jasp = in_jasp(
        tmp_path,
        ["jaspReliability"],
        "out <- list(alpha = Bayesrel:::applyalpha(cov(d, use = 'pairwise.complete.obs')))",
        items,
    )
    assert summary.alpha == pytest.approx(jasp["alpha"], rel=1e-10)


def cfa_model(result):
    models = cfa.build_models(result.project, result.catalog, result.datasets)
    return next(
        m
        for m in models
        if (m.instrument_id, m.dataset, m.kind) == ("example_mood", "child_w1", cfa.SUBSCALES)
    )


def lavaan_syntax(factors: dict[str, list[str]], columns: dict[str, str]) -> str:
    return "\n".join(
        f"F{j} =~ " + " + ".join(columns[c] for c in members)
        for j, members in enumerate(factors.values(), start=1)
    )


JASP_CFA = """
items <- setdiff(names(d), "g")
{ordered}
fit <- lavaan::lavaan(
  model = "{syntax}", data = d, group = {group}, group.equal = {equal},
  std.lv = FALSE, auto.fix.first = TRUE, orthogonal = FALSE, int.ov.free = TRUE,
  int.lv.free = FALSE, auto.fix.single = TRUE, auto.var = TRUE, auto.cov.lv.x = TRUE,
  auto.th = TRUE, auto.delta = TRUE, auto.cov.y = TRUE, mimic = "lavaan",
  estimator = "default", missing = "listwise")
measures <- lavaan::fitMeasures(fit, {measures})
out <- as.list(measures)
"""
ORDINAL_MEASURES = (
    'c("chisq.scaled", "df.scaled", "cfi.scaled", "rmsea.scaled", "rmsea.ci.lower.scaled", '
    '"rmsea.ci.upper.scaled", "srmr")'
)
CONTINUOUS_MEASURES = 'c("chisq", "df", "cfi", "rmsea", "rmsea.ci.lower", "rmsea.ci.upper", "srmr")'


def jasp_cfa(tmp_path, data, factors, ordinal, group="NULL", equal='""') -> dict:
    # jaspFactor: lavaan::lavaan with JASP's defaults, a marker item per factor; items set to
    # ordinal in JASP become ordered factors.
    columns = {c: f"x{i}" for i, c in enumerate(dict.fromkeys(sum(factors.values(), [])), 1)}
    code = JASP_CFA.format(
        ordered="for (i in items) d[[i]] <- ordered(d[[i]])" if ordinal else "",
        syntax=lavaan_syntax(factors, columns).replace("\n", "; "),
        group=group,
        equal=equal,
        measures=ORDINAL_MEASURES if ordinal else CONTINUOUS_MEASURES,
    )
    return in_jasp(tmp_path, ["jaspFactor"], code, data.rename(columns=columns))


def fit_keys(found: dict) -> dict:
    names = {"rmsea.ci.lower": "rmsea_low", "rmsea.ci.upper": "rmsea_high"}
    keys = (k.removesuffix(".scaled") for k in found)
    return {names.get(k, k): v for k, v in zip(keys, found.values(), strict=True)}


@pytest.mark.skipif(not ready(CFA_PACKAGES), reason="R with lavaan and semTools is not installed")
def test_ordinal_cfa_fit_matches_jasp(result, tmp_path):
    model = cfa_model(result)
    [fit] = cfa.fit_models([model], rscript(), cfa.WLSMV)
    jasp = fit_keys(jasp_cfa(tmp_path, model.data, model.factors, ordinal=True))
    for key in ("chisq", "df", "cfi", "rmsea", "rmsea_low", "rmsea_high", "srmr"):
        assert fit.fit[key] == pytest.approx(jasp[key], rel=1e-4, abs=1e-6), key


@pytest.mark.skipif(not ready(CFA_PACKAGES), reason="R with lavaan and semTools is not installed")
def test_second_order_fit_and_hierarchical_omega_match_jasp(result, tmp_path):
    models = cfa.build_models(result.project, result.catalog, result.datasets)
    model = next(
        m
        for m in models
        if (m.instrument_id, m.dataset, m.kind) == ("example_mood", "child_w1", cfa.SECOND_ORDER)
    )
    [fit] = cfa.fit_models([model], rscript(), cfa.WLSMV)
    # jaspFactor's Second-Order box adds SecondOrder =~ over the factors; its reliability table
    # takes semTools' omega with higher = "SecondOrder" (semTools 0.5-7 in JASP), which with
    # ordered items drops that omega when return.total is also set, so it is left out here.
    columns = {c: f"x{i}" for i, c in enumerate(model.data.columns, 1)}
    syntax = lavaan_syntax(model.factors, columns)
    syntax += "\nSecondOrder =~ " + " + ".join(f"F{j}" for j in range(1, len(model.factors) + 1))
    code = JASP_CFA.format(
        ordered="for (i in items) d[[i]] <- ordered(d[[i]])",
        syntax=syntax.replace("\n", "; "),
        group="NULL",
        equal='""',
        measures=ORDINAL_MEASURES,
    )
    code += 'out$omega <- semTools::compRelSEM(fit, higher = "SecondOrder")[["SecondOrder"]]\n'
    jasp = fit_keys(in_jasp(tmp_path, ["jaspFactor"], code, model.data.rename(columns=columns)))
    for key in ("chisq", "df", "cfi", "rmsea", "rmsea_low", "rmsea_high", "srmr"):
        assert fit.fit[key] == pytest.approx(jasp[key], rel=1e-4, abs=1e-6), key
    assert fit.general_omega == pytest.approx(jasp["omega"], rel=1e-4)


@pytest.mark.parametrize("engine", engines(CFA_PACKAGES))
def test_continuous_cfa_fit_matches_jasp(result, tmp_path, engine):
    model = cfa_model(result)
    [fit] = cfa.fit_models([model], engine, cfa.ML)
    jasp = fit_keys(jasp_cfa(tmp_path, model.data, model.factors, ordinal=False))
    # semopy and lavaan reach the same maximum by different optimizers; semopy has no interval.
    close = 1e-6 if engine else 1e-3
    keys = ("chisq", "df", "cfi", "rmsea") + (("rmsea_low", "rmsea_high") if engine else ())
    for key in keys:
        assert fit.fit[key] == pytest.approx(jasp[key], rel=close, abs=close), key


@pytest.mark.skipif(not ready(CFA_PACKAGES), reason="R with lavaan and semTools is not installed")
def test_multigroup_invariance_matches_jasp_for_continuous_items(result, sample, tmp_path):
    [model] = group_invariance.group_models(result, sample, "example_mood@child_w1", GENDER)
    [test] = invariance.fit_models([model], rscript(), "ml")
    data = pd.concat(
        [frame.assign(g=label) for label, frame in model.occasions.items()], ignore_index=True
    )
    equal = {
        "configural": '""',
        "metric": '"loadings"',
        "scalar": 'c("loadings", "intercepts")',
    }
    for step in test.steps:
        jasp = jasp_cfa(tmp_path, data, model.factors, False, '"g"', equal[step.step])
        for key in ("chisq", "df", "cfi", "rmsea"):
            assert step.fit[key] == pytest.approx(jasp[key], rel=1e-5, abs=1e-6), (step, key)


@pytest.mark.skipif(not ready(CFA_PACKAGES), reason="R with lavaan and semTools is not installed")
def test_multigroup_configural_model_matches_jasp_for_ordered_items(result, tmp_path):
    # The whole wave, so that both groups use every option.
    sample = analysis.build_sample(result, ["parent_w1", "child_w1"], False)
    [model] = group_invariance.group_models(result, sample, "example_mood@child_w1", GENDER)
    [test] = invariance.fit_models([model], rscript(), "wlsmv")
    assert test.problem is None, test.problem
    data = pd.concat(
        [frame.assign(g=label) for label, frame in model.occasions.items()], ignore_index=True
    )
    jasp = fit_keys(jasp_cfa(tmp_path, data, model.factors, True, '"g"'))
    configural = test.steps[0]
    for key in ("chisq", "df", "cfi", "rmsea"):
        assert configural.fit[key] == pytest.approx(jasp[key], rel=1e-4, abs=1e-6), key


@pytest.mark.parametrize("engine", engines(MULTILEVEL_PACKAGES))
def test_growth_model_matches_jasp_mixed_models(result, tmp_path, engine):
    model = ml.Model(EMS.split("@")[0], ["child_w1", "child_w2", "child_w3"])
    long = ml.long_frame(result, model)
    fitted = ml.run(result, model, long, "EMS", engine)
    # jaspMixedModels: afex::mixed with Satterthwaite's df, type III, contrasts as given.
    jasp = in_jasp(
        tmp_path,
        ["jaspMixedModels"],
        f"""
fit <- afex::mixed({long.outcome} ~ {ml.TIME} + ({ml.TIME} | {ml.PERSON}), data = d,
                   type = "3", method = "S", check_contrasts = FALSE)
table <- summary(fit$full_model)$coefficients
out <- list(b0 = table[1, "Estimate"], se0 = table[1, "Std. Error"], df0 = table[1, "df"],
            b1 = table[2, "Estimate"], se1 = table[2, "Std. Error"], df1 = table[2, "df"],
            p1 = table[2, "Pr(>|t|)"])
""",
        long.frame,
    )
    intercept, time = fitted.fixed[0], fitted.fixed[1]
    if engine is None:
        # statsmodels has no Satterthwaite df; its optimizer stops close to lme4's.
        assert (intercept.estimate, time.estimate) == pytest.approx(
            (jasp["b0"], jasp["b1"]), abs=0.01 * jasp["se1"]
        )
        assert (intercept.se, time.se) == pytest.approx((jasp["se0"], jasp["se1"]), rel=0.05)
        return
    assert (intercept.estimate, intercept.se, intercept.df) == pytest.approx(
        (jasp["b0"], jasp["se0"], jasp["df0"]), rel=1e-4
    )
    assert (time.estimate, time.se, time.df, time.p) == pytest.approx(
        (jasp["b1"], jasp["se1"], jasp["df1"], jasp["p1"]), rel=1e-4
    )


@pytest.mark.parametrize("engine", engines())
def test_spearman_matches_jasp(result, sample, tmp_path, engine):
    data = script.AnalysisData(result, sample)
    x, y = data.score(EPS), data.score(EMS)
    frame = data.frame()
    code = script.correlation_code([x, y], "spearman")
    found, _ = script.run_code(result, sample, frame, code, engine)
    _, matrix = script.read_correlations(found, [x.column, y.column])
    # jaspRegression: cor.test with its default exact = NULL.
    jasp = in_jasp(
        tmp_path,
        ["jaspRegression"],
        f"""
test <- suppressWarnings(cor.test(d[["{x.column}"]], d[["{y.column}"]], method = "spearman"))
out <- list(r = test$estimate, p = test$p.value)
""",
        frame,
    )
    assert (matrix[1][0].r, matrix[1][0].p) == pytest.approx((jasp["r"], jasp["p"]), rel=1e-6)


@pytest.mark.skipif(not ready(ANALYSIS_PACKAGES), reason="R with psych is not installed")
def test_spearman_p_is_exact_in_r_without_ties(result, sample, tmp_path):
    data = script.AnalysisData(result, sample)
    x, y = data.score(EPS), data.score(EMS)
    frame = data.frame()
    # Without ties JASP's cor.test gives the exact p, which the t approximation misses.
    frame[x.column] += [i * 1e-6 for i in range(len(frame))]
    frame[y.column] -= [i * 1e-7 for i in range(len(frame))]
    code = script.correlation_code([x, y], "spearman")
    found, _ = script.run_code(result, sample, frame, code, rscript())
    _, matrix = script.read_correlations(found, [x.column, y.column])
    jasp = in_jasp(
        tmp_path,
        ["jaspRegression"],
        f"""
test <- cor.test(d[["{x.column}"]], d[["{y.column}"]], method = "spearman")
out <- list(r = test$estimate, p = test$p.value)
""",
        frame,
    )
    assert (matrix[1][0].r, matrix[1][0].p) == pytest.approx((jasp["r"], jasp["p"]), rel=1e-6)
    found, _ = script.run_code(result, sample, frame, code, None)
    _, approximated = script.read_correlations(found, [x.column, y.column])
    assert approximated[1][0].p != pytest.approx(jasp["p"], rel=1e-4)


def test_item_rest_r_and_alpha_without_the_item_match_jasp(result, tmp_path):
    summary = next(s for s in result.summary.scores if s.key == EMS)
    score = next(s for s in result.catalog.scores if s.key == EMS)
    items = score_items(result.datasets["child_w1"], score)
    # jaspReliability: the item against the sum of the others, and alpha with its row and column
    # taken out of the pairwise covariances.
    jasp = in_jasp(
        tmp_path,
        ["jaspReliability"],
        """
cc <- cov(d, use = "pairwise.complete.obs")
out <- list()
for (i in seq_len(ncol(d))) {
  out[[paste0("alpha", i)]] <- Bayesrel:::applyalpha(cc[-i, -i])
  out[[paste0("r", i)]] <- cor(d[, i], rowSums(as.matrix(d[, -i]), na.rm = TRUE),
                               use = "pairwise.complete.obs")
}
""",
        items,
    )
    assert [t.column for t in summary.item_total] == list(items.columns)
    for i, total in enumerate(summary.item_total, 1):
        assert (total.r, total.alpha_if_deleted) == pytest.approx(
            (jasp[f"r{i}"], jasp[f"alpha{i}"]), rel=1e-10
        )


@pytest.mark.parametrize("engine", engines())
def test_attrition_chi_square_matches_jasp(result, tmp_path, engine):
    plan = attrition.plan(result, "mock_study", "1", ["item:example_demographics.dem_gender"])
    found, _ = script.run_code(result, plan.sample, plan.frame, plan.code, engine)
    [gender] = attrition.read(found, plan.labels)
    column = next(c for c in plan.frame.columns if c.startswith("dem_gender"))
    # jaspFrequencies: the chi-square row of Contingency Tables, without continuity correction.
    jasp = in_jasp(
        tmp_path,
        ["jaspFrequencies"],
        f"""
test <- chisq.test(table(d[["{column}"]], d[["{attrition.RETURNED}"]]), correct = FALSE)
out <- list(chi = test$statistic, df = test$parameter, p = test$p.value)
""",
        plan.frame,
    )
    assert (gender.test.statistic, gender.test.df, gender.test.p) == pytest.approx(
        (jasp["chi"], jasp["df"], jasp["p"]), rel=1e-6
    )


@pytest.mark.parametrize("engine", engines())
def test_table_one_matches_jasp_descriptives(result, sample, tmp_path, engine):
    data = script.AnalysisData(result, sample)
    rows = script.measure_variables(data, script.default_measures(result, sample.datasets), True)
    code = script.table_one_code(sample.datasets, rows)
    frame = data.frame()
    found, _ = script.run_code(result, sample, frame, code, engine)
    table = found["table1"]
    variables = [v for _, vs in rows for v in vs]
    numbers = [v for v in variables if v.kind != script.CHOICE]
    choices = [v for v in variables if v.kind == script.CHOICE]
    # Descriptives and Frequencies: mean, sd and valid n, and the percent of those who answered;
    # alpha as in jaspReliability.
    lines = ["out <- list()"]
    for i, v in enumerate(numbers):
        lines.append(
            f'x <- d[["{v.column}"]]; out[["n{i}"]] <- sum(!is.na(x)); '
            f'out[["mean{i}"]] <- mean(x, na.rm = TRUE); out[["sd{i}"]] <- sd(x, na.rm = TRUE)'
        )
        if v.items:
            columns = ", ".join(f'"{c}"' for c in v.items)
            lines.append(
                f'out[["alpha{i}"]] <- Bayesrel:::applyalpha(cov(d[c({columns})], '
                'use = "pairwise.complete.obs"))'
            )
    for i, v in enumerate(choices):
        for j, (value, _) in enumerate(v.options):
            lines.append(
                f'x <- d[["{v.column}"]]; '
                f'out[["share{i}_{j}"]] <- 100 * sum(x == {value}, na.rm = TRUE) / sum(!is.na(x))'
            )
    jasp = in_jasp(tmp_path, ["jaspReliability"], "\n".join(lines), frame)
    assert numbers and choices
    for i, v in enumerate(numbers):
        [row] = table[(table["variable"] == v.label) & (table["dataset"] == v.dataset)].itertuples()
        assert (row.n, row.mean, row.sd) == pytest.approx(
            (jasp[f"n{i}"], jasp[f"mean{i}"], jasp[f"sd{i}"]), rel=1e-10
        ), v.label
        if v.items:
            assert row.alpha == pytest.approx(jasp[f"alpha{i}"], rel=1e-8), v.label
    for i, v in enumerate(choices):
        shown = table[(table["variable"] == v.label) & (table["dataset"] == v.dataset)]
        expected = [jasp[f"share{i}_{j}"] for j in range(len(v.options))]
        assert shown["percent"].tolist() == pytest.approx(expected, rel=1e-10), v.label
