from labcatalog.stats.analysis_script import Code, Variable, r_string
from labcatalog.stats.cfa import ML, MLR, WLSMV
from labcatalog.stats.mediation import (
    BASE,
    DEFAULT_WORKERS,
    ESTIMATOR_NAMES,
    FIT,
    MODSEM,
    SEED,
    MediationModel,
)

AT = """\
at <- function(template) {
  paste(sprintf(template, seq_along(w_at), sprintf("(%.12g)", w_at)), collapse = "\\n")
}"""
OBSERVED_AT = """\
# Conditional effects at the moderator's two answers, or at its mean and 1 SD either side.
w_levels <- sort(unique(med$w))
w_at <- if (length(w_levels) == 2) w_levels else c(-1, 0, 1) * sd(med$w)"""
CENTRE_SCORES = """\
w_mean <- mean(med$w)
# Centred, so each path is its effect where the other variables are at their means.
for (v in c("x", "m", "w")) med[[v]] <- med[[v]] - mean(med[[v]])
med$xw <- med$x * med$w
med$mw <- med$m * med$w"""
CENTRE_W = """\
w_mean <- mean(med$w)
# Centred, so each path is its effect at the moderator's mean; the factors have mean 0.
med$w <- med$w - w_mean"""
LATENT_AT = """\
# Fitted once without the conditional effects, for the SD of the moderator's factor.
first <- modsem::modsem(base, data = med, method = "lms")
found <- modsem::parameter_estimates(first)
w_sd <- sqrt(found$est[found$lhs == "W" & found$op == "~~" & found$rhs == "W"])
w_mean <- 0
w_at <- c(-1, 0, 1) * w_sd"""
COUNT = """\
# Resamples that converged, of those asked for.
resamples <- sum(complete.cases(lavaan::lavInspect(fit, "boot")))"""
LAVAAN_EFFECTS = """\
estimates <- estimates[estimates$label != "", ]
std <- lavaan::standardizedSolution(fit, se = FALSE)
effects <- data.frame(label = estimates$label, est = estimates$est, se = estimates$se,
                      pvalue = estimates$pvalue, ci.lower = estimates$ci.lower,
                      ci.upper = estimates$ci.upper,
                      std = std$est.std[match(estimates$label, std$label)])"""
MODSEM_BOOTSTRAP = """\
# Each resample refits the model; the intervals are the 2.5th and 97.5th percentiles.
set.seed({seed})
boot <- modsem::bootstrap_modsem(fit, FUN = function(f) {{
  found <- modsem::parameter_estimates(f)
  found$est[match(estimates$label, found$label)]
}}, R = {bootstrap})
resamples <- sum(complete.cases(boot))
estimates$std.error <- apply(boot, 2, sd, na.rm = TRUE)
estimates$p.value <- 2 * pnorm(-abs(estimates$est / estimates$std.error))
estimates$ci.lower <- apply(boot, 2, quantile, 0.025, na.rm = TRUE)
estimates$ci.upper <- apply(boot, 2, quantile, 0.975, na.rm = TRUE)"""
MODSEM_EFFECTS = """\
std <- modsem::standardized_estimates(fit)
effects <- data.frame(label = estimates$label, est = estimates$est, se = estimates$std.error,
                      pvalue = estimates$p.value, ci.lower = estimates$ci.lower,
                      ci.upper = estimates$ci.upper,
                      std = std$est[match(estimates$label, std$label)])"""


def mediation_code(model: MediationModel, workers: int = DEFAULT_WORKERS) -> Code:
    w = model.moderators[0].variable if model.moderators else None
    roles = {"x": model.x, "m": model.m, "y": model.y} | ({"w": w} if w is not None else {})
    latent = {r for r, v in roles.items() if model.items and v.items}
    columns, measurement = data_columns(model, roles, latent)
    booted = model.bootstrap > 0
    lines = [
        f"# Mediation: {title(model)}. {model.package}, {estimation_text(model)}; "
        f"{intervals_phrase(model)}.",
        f"# {'; '.join(f'{name(r, latent)} = {v.label}' for r, v in roles.items())}",
        f"med <- data.frame({', '.join(columns)})",
        "med <- med[complete.cases(med), ]",
    ]
    structure = [*measurement, *equations(model, latent)]
    if model.package == MODSEM:
        lines += modsem_lines(model, structure, booted)
    else:
        lines += lavaan_lines(model, structure, latent, booted, workers)
    lines += [
        "print(effects)",
        "model_fit <- data.frame(c(list(n = nrow(med), resamples = resamples),",
        "                          as.list(unclass(measures))), check.names = FALSE)",
        "print(model_fit)",
        f"moderator_values <- data.frame(value = {'w_at + w_mean' if w else 'numeric(0)'})",
        "",
    ]
    return Code(
        title="Mediation",
        r="\n".join(lines),
        python="",
        outputs=("effects", "model_fit", "moderator_values"),
        packages=("lavaan", "modsem") if model.package == MODSEM else ("lavaan",),
    )


def name(role: str, latent: set[str]) -> str:
    # Factors are upper case, observed variables lower case, as in the model syntax.
    return role.upper() if role in latent else role


def title(model: MediationModel) -> str:
    text = f"{model.x.label} to {model.y.label} through {model.m.label}"
    if model.moderators:
        text += f", moderated by {model.moderators[0].variable.label}"
    return text


def data_columns(
    model: MediationModel, roles: dict[str, Variable], latent: set[str]
) -> tuple[list[str], list[str]]:
    columns, measurement = [], []
    for role, v in roles.items():
        if role in latent:
            names = [f"{role}_{i}" for i in range(1, len(v.items) + 1)]
            columns += [f"{n} = d[[{r_string(c)}]]" for n, c in zip(names, v.items, strict=True)]
            measurement.append(f"{role.upper()} =~ {' + '.join(names)}")
        else:
            columns.append(f"{role} = d[[{r_string(v.column)}]]")
    columns += [f"cov{i} = d[[{r_string(v.column)}]]" for i, v in enumerate(model.covariates, 1)]
    return columns, measurement


def equations(model: MediationModel, latent: set[str]) -> list[str]:
    moderated = model.moderated
    x, m, y, w = (name(r, latent) for r in ("x", "m", "y", "w"))
    # Observed scores interact through product columns, factors through modsem's colon.
    joined = model.package == MODSEM
    xw = f"{x}:{w}" if joined else "xw"
    mw = f"{m}:{w}" if joined else "mw"
    covariates = "".join(f" + cov{i}" for i in range(1, len(model.covariates) + 1))
    m_terms = [f"a*{x}"] + ([f"a_w*{w}", f"a_xw*{xw}"] if "a" in moderated else [])
    y_terms = [f"c*{x}", f"b*{m}"]
    if moderated & {"b", "c"}:
        y_terms.append(f"y_w*{w}")
    if "b" in moderated:
        y_terms.append(f"b_mw*{mw}")
    if "c" in moderated:
        y_terms.append(f"c_xw*{xw}")
    return [f"{m} ~ {' + '.join(m_terms)}{covariates}", f"{y} ~ {' + '.join(y_terms)}{covariates}"]


def model_lines(structure: list[str], moderated: set[str], base: str = "") -> list[str]:
    parts = [base] if base else [r_string(s) for s in structure]
    parts += definition_lines(moderated)
    return ["model <- paste(", *(f"  {p}," for p in parts), '  sep = "\\n"', ")"]


def lavaan_lines(
    model: MediationModel, structure: list[str], latent: set[str], booted: bool, workers: int
) -> list[str]:
    lines = []
    if model.moderators:
        lines += [CENTRE_SCORES, OBSERVED_AT, AT]
    lines += model_lines(structure, model.moderated)
    ordered = ""
    if model.estimator == WLSMV:
        names = [
            f"{r}_{i}" for r in sorted(latent) for i in range(1, len(roles_items(model, r)) + 1)
        ]
        lines.append(f"ordered <- c({', '.join(r_string(n) for n in names)})")
        ordered = ", ordered = ordered"
    chosen = model.estimator.upper()
    if booted:
        parallel = f', parallel = "snow", ncpus = {workers}' if workers > 1 else ""
        robust = model.estimator != ML
        if robust:
            lines.append(
                f"# Bootstrap needs plain {BASE[model.estimator]}, whose estimates are "
                f"{chosen}'s too; {chosen}'s fit comes from a second fit."
            )
        lines += [
            f'fit <- lavaan::sem(model, data = med, estimator = "{BASE[model.estimator]}"{ordered},',
            f'                   se = "bootstrap", bootstrap = {model.bootstrap}, '
            f"iseed = {SEED}{parallel})",
            'estimates <- lavaan::parameterEstimates(fit, boot.ci.type = "perc")',
            COUNT,
        ]
        fitted = "fit"
        if robust:
            lines.append(
                f'robust <- lavaan::sem(model, data = med, estimator = "{chosen}"{ordered})'
            )
            fitted = "robust"
    else:
        lines += [
            f'fit <- lavaan::sem(model, data = med, estimator = "{chosen}"{ordered})',
            "estimates <- lavaan::parameterEstimates(fit)",
            "resamples <- 0",
        ]
        fitted = "fit"
    measures = ", ".join(r_string(m) for m in FIT[model.estimator])
    lines += [LAVAAN_EFFECTS, f"measures <- lavaan::fitMeasures({fitted}, c({measures}))"]
    return lines


def roles_items(model: MediationModel, role: str) -> list[str]:
    return {"x": model.x, "m": model.m, "y": model.y}[role].items


def modsem_lines(model: MediationModel, structure: list[str], booted: bool) -> list[str]:
    robust = ", robust.se = TRUE" if model.estimator == MLR else ""
    lines = [
        "base <- paste(",
        *(f"  {r_string(s)}," for s in structure),
        '  sep = "\\n"',
        ")",
    ]
    lines += [LATENT_AT] if model.latent_moderator else [CENTRE_W, OBSERVED_AT]
    lines += [AT, *model_lines(structure, model.moderated, base="base")]
    lines += [
        f'fit <- modsem::modsem(model, data = med, method = "{model.method}"{robust})',
        "estimates <- modsem::parameter_estimates(fit)",
        'estimates <- estimates[estimates$label != "", ]',
    ]
    if booted:
        lines.append(MODSEM_BOOTSTRAP.format(seed=SEED, bootstrap=model.bootstrap))
    else:
        lines.append("resamples <- 0")
    # The latent interaction leaves no chi-square test of the model's fit.
    lines += [MODSEM_EFFECTS, "measures <- c()"]
    return lines


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


def estimation_text(model: MediationModel) -> str:
    if model.package == MODSEM:
        return f"latent interactions by {model.method.upper()}, {ESTIMATOR_NAMES[model.estimator]}"
    if model.bootstrap and model.estimator != ML:
        return f"{ESTIMATOR_NAMES[model.estimator]} for the model's fit"
    return ESTIMATOR_NAMES[model.estimator]


def intervals_phrase(model: MediationModel) -> str:
    if model.bootstrap:
        return f"percentile bootstrap CIs from {model.bootstrap} resamples"
    return "Wald CIs, by the delta method for the defined effects"
