from dataclasses import dataclass, field

import pandas as pd

from labcatalog.stats.analysis_script import Code, Variable, none, r_string
from labcatalog.stats.cfa import ML, MLR

PATHS = ("a", "b", "c")
SCORE_ESTIMATORS = (ML, MLR)
DEFAULT_BOOTSTRAP = 1000
DEFAULT_WORKERS = 4
SEED = 1
ESTIMATOR_NAMES = {ML: "maximum likelihood", MLR: "robust maximum likelihood (MLR)"}
FIT = {
    ML: ("chisq", "df", "pvalue", "cfi", "tli", "rmsea", "srmr"),
    MLR: (
        "chisq.scaled",
        "df.scaled",
        "pvalue.scaled",
        "cfi.robust",
        "tli.robust",
        "rmsea.robust",
        "srmr",
    ),
}
FIT_NAMES = {
    "chisq.scaled": "chisq",
    "df.scaled": "df",
    "pvalue.scaled": "pvalue",
    "cfi.robust": "cfi",
    "tli.robust": "tli",
    "rmsea.robust": "rmsea",
}


@dataclass
class Moderator:
    variable: Variable
    # Which of a (X to M), b (M to Y) and c (X to Y, the direct effect) it moderates.
    paths: tuple[str, ...]


@dataclass
class MediationModel:
    x: Variable
    m: Variable
    y: Variable
    covariates: list[Variable] = field(default_factory=list)
    # One for now; a list so that a second can come later.
    moderators: list[Moderator] = field(default_factory=list)
    estimator: str = ML
    bootstrap: int = DEFAULT_BOOTSTRAP

    @property
    def moderated(self) -> set[str]:
        return {p for m in self.moderators for p in m.paths}


@dataclass
class Effect:
    label: str
    estimate: float
    se: float | None
    p: float | None
    low: float | None
    high: float | None


@dataclass
class MediationFit:
    n: int
    # Keyed by lavaan label: a, b, c, a_w, a_xw, y_w, b_mw, c_xw, indirect, total, index,
    # indirect_<k> and direct_<k> at the moderator's k-th value.
    effects: dict[str, Effect]
    fit: dict[str, float | None]
    # The moderator's values, in its own units, at which the conditional effects are taken.
    at: list[float] = field(default_factory=list)
    estimator: str = ML
    bootstrap: int = DEFAULT_BOOTSTRAP
    resamples: int = DEFAULT_BOOTSTRAP


R_MEDIATION = """\
# Mediation: {title}. lavaan, {method}; {intervals}.
# x, m, y{w_name}: {legend}
med <- data.frame({columns})
med <- med[complete.cases(med), ]
{moderator_prep}model <- paste(
  {m_equation},
  {y_equation},
  {definitions},
  sep = "\\n"
)
{estimation}effects <- estimates[estimates$label != "", c("label", "est", "se", "pvalue", "ci.lower",
                                              "ci.upper")]
print(effects)
{fit_line}measures <- lavaan::fitMeasures({fitted}, c({measures}))
{resamples}model_fit <- data.frame(n = nrow(med), resamples = resamples, as.list(unclass(measures)),
                        check.names = FALSE)
print(model_fit)
moderator_values <- data.frame(value = {values})
"""
BOOTSTRAP = """\
{robust}fit <- lavaan::sem(model, data = med, estimator = "ML", se = "bootstrap",
                   bootstrap = {bootstrap}, iseed = {seed}{parallel})
estimates <- lavaan::parameterEstimates(fit, boot.ci.type = "perc")
"""
COUNT = """\
# Resamples that converged, of those asked for.
resamples <- sum(complete.cases(lavaan::lavInspect(fit, "boot")))
"""
NO_BOOTSTRAP = """\
fit <- lavaan::sem(model, data = med, estimator = "{estimator}")
estimates <- lavaan::parameterEstimates(fit)
"""
MODERATOR_PREP = """\
w_mean <- mean(med$w)
# Centred, so each path is its effect where the other variables are at their means.
for (v in c("x", "m", "w")) med[[v]] <- med[[v]] - mean(med[[v]])
med$xw <- med$x * med$w
med$mw <- med$m * med$w
# Conditional effects at the moderator's two answers, or at its mean and 1 SD either side.
w_levels <- sort(unique(med$w))
w_at <- if (length(w_levels) == 2) w_levels else c(-1, 0, 1) * sd(med$w)
at <- function(template) {
  paste(sprintf(template, seq_along(w_at), sprintf("(%.12g)", w_at)), collapse = "\\n")
}
"""


def mediation_code(model: MediationModel, workers: int = DEFAULT_WORKERS) -> Code:
    moderated = model.moderated
    w = model.moderators[0].variable if model.moderators else None
    names = {"x": model.x, "m": model.m, "y": model.y}
    if w is not None:
        names["w"] = w
    names |= {f"cov{i}": v for i, v in enumerate(model.covariates, start=1)}
    columns = ", ".join(f"{n} = d[[{r_string(v.column)}]]" for n, v in names.items())
    legend = "; ".join(f"{n} = {v.label}" for n, v in names.items())
    covariates = "".join(f" + cov{i}" for i in range(1, len(model.covariates) + 1))
    m_terms = ["a*x"] + (["a_w*w", "a_xw*xw"] if "a" in moderated else [])
    y_terms = ["c*x", "b*m"]
    if moderated & {"b", "c"}:
        y_terms.append("y_w*w")
    if "b" in moderated:
        y_terms.append("b_mw*mw")
    if "c" in moderated:
        y_terms.append("c_xw*xw")
    definitions = definition_lines(moderated)
    booted = model.bootstrap > 0
    # Bootstrap needs plain ML, so MLR's fit comes from a second fit.
    robust = model.estimator == MLR and booted
    estimation = (
        BOOTSTRAP.format(
            robust="# Bootstrap needs plain ML; its estimates are MLR's too, whose fit is below.\n"
            if robust
            else "",
            bootstrap=model.bootstrap,
            seed=SEED,
            parallel=f', parallel = "snow", ncpus = {workers}' if workers > 1 else "",
        )
        if booted
        else NO_BOOTSTRAP.format(estimator=model.estimator.upper())
    )
    title = f"{model.x.label} to {model.y.label} through {model.m.label}"
    if w is not None:
        title += f", moderated by {w.label}"
    r = R_MEDIATION.format(
        title=title,
        method="robust maximum likelihood (MLR) for the model's fit"
        if robust
        else ESTIMATOR_NAMES[model.estimator],
        intervals=f"percentile bootstrap CIs from {model.bootstrap} resamples"
        if booted
        else "Wald CIs, by the delta method for the defined effects",
        estimation=estimation,
        resamples=COUNT if booted else "resamples <- 0\n",
        w_name=", w" if w is not None else "",
        legend=legend,
        columns=columns,
        moderator_prep=MODERATOR_PREP if w is not None else "",
        m_equation=r_string(f"m ~ {' + '.join(m_terms)}{covariates}"),
        y_equation=r_string(f"y ~ {' + '.join(y_terms)}{covariates}"),
        definitions=",\n  ".join(definitions),
        fit_line='robust <- lavaan::sem(model, data = med, estimator = "MLR")\n' if robust else "",
        fitted="robust" if robust else "fit",
        measures=", ".join(r_string(m) for m in FIT[model.estimator]),
        values="w_at + w_mean" if w is not None else "numeric(0)",
    )
    return Code(
        title="Mediation",
        r=r,
        python="",
        outputs=("effects", "model_fit", "moderator_values"),
        packages=("lavaan",),
    )


def definition_lines(moderated: set[str]) -> list[str]:
    # R expressions that give the syntax of the defined effects.
    if not moderated:
        return [r_string("indirect := a*b"), r_string("total := c + a*b")]
    a = "(a + a_xw*%2$s)" if "a" in moderated else "a"
    b = "(b + b_mw*%2$s)" if "b" in moderated else "b"
    lines = (
        [f"at({r_string(f'indirect_%1$d := {a}*{b}')})"]
        if moderated & {"a", "b"}
        else [r_string("indirect := a*b")]
    )
    if "c" in moderated:
        lines.append(f"at({r_string('direct_%1$d := c + c_xw*%2$s')})")
    # With one of a and b moderated, the indirect effect is linear in the moderator.
    if moderated & {"a", "b"} == {"a"}:
        lines.append(r_string("index := a_xw*b"))
    elif moderated & {"a", "b"} == {"b"}:
        lines.append(r_string("index := a*b_mw"))
    return lines


def read_fit(found: dict[str, pd.DataFrame], model: MediationModel) -> MediationFit:
    effects = {
        row.label: Effect(
            row.label,
            float(row.est),
            none(row.se),
            none(row.pvalue),
            none(row["ci.lower"]),
            none(row["ci.upper"]),
        )
        for _, row in found["effects"].iterrows()
    }
    measures = found["model_fit"].iloc[0]
    fit = {FIT_NAMES.get(k, k): none(measures[k]) for k in FIT[model.estimator]}
    return MediationFit(
        n=int(measures["n"]),
        effects=effects,
        fit=fit,
        at=[float(v) for v in found["moderator_values"]["value"]],
        estimator=model.estimator,
        bootstrap=model.bootstrap,
        resamples=int(measures["resamples"]),
    )


def at_labels(model: MediationModel, fit: MediationFit) -> list[str]:
    # Where the conditional effects are taken, in words.
    if not model.moderators:
        return []
    w = model.moderators[0].variable
    if len(fit.at) == 2:
        options = dict(w.options)
        return [options.get(v, f"{v:g}") for v in fit.at]
    return ["1 SD below the mean", "the mean", "1 SD above the mean"]


def intervals_text(fit: MediationFit) -> str:
    if not fit.bootstrap:
        return "Wald intervals, by the delta method for the defined effects"
    done = (
        fit.bootstrap if fit.resamples >= fit.bootstrap else f"{fit.resamples} of {fit.bootstrap}"
    )
    return f"percentile bootstrap intervals from {done} resamples"


def method_text(fit: MediationFit) -> str:
    if fit.estimator == MLR and fit.bootstrap:
        return (
            "maximum likelihood for the estimates and robust maximum likelihood (MLR) for the fit"
        )
    return ESTIMATOR_NAMES[fit.estimator]
