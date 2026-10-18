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
    depends,
    index_label,
    indexed,
)

AT = """\
# Each conditional effect at every combination of the moderators' values it varies with.
at <- function(template, ...) {
  values <- list(...)
  grid <- expand.grid(lapply(values, seq_along))
  lines <- apply(grid, 1, function(k) {
    picked <- mapply(function(v, i) sprintf("(%.12g)", v[i]), values, k)
    do.call(sprintf, c(list(template), as.list(k), as.list(picked)))
  })
  paste(lines, collapse = "\\n")
}"""
OBSERVED_NOTE = (
    "# Conditional effects at the moderator's two answers, or at its mean and 1 SD either side."
)
OBSERVED_AT = """\
{w}_levels <- sort(unique(med${w}))
{w}_at <- if (length({w}_levels) == 2) {w}_levels else c(-1, 0, 1) * sd(med${w})"""
CENTRE_W = """\
{w}_mean <- mean(med${w})
# Centred, so each path is its effect at the moderator's mean; the factors have mean 0.
med${w} <- med${w} - {w}_mean"""
FIRST_FIT = """\
# Fitted once without the conditional effects, for the SD of the moderator's factor.
first <- modsem::modsem(base, data = med, method = "{method}")
found <- modsem::parameter_estimates(first)"""
LATENT_AT = """\
{w}_sd <- sqrt(found$est[found$lhs == "{factor}" & found$op == "~~" & found$rhs == "{factor}"])
{w}_mean <- 0
{w}_at <- c(-1, 0, 1) * {w}_sd"""
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
    roles = {"x": model.x, "m": model.m, "y": model.y} | {
        f"w{s}": m.variable for s, m in zip(model.tags, model.moderators, strict=True)
    }
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
        moderator_values(model),
        "",
    ]
    return Code(
        title="Mediation",
        r="\n".join(lines),
        python="",
        outputs=("effects", "model_fit", "moderator_values"),
        packages=("lavaan", "modsem") if model.package == MODSEM else ("lavaan",),
    )


def moderator_values(model: MediationModel) -> str:
    if not model.moderators:
        return "moderator_values <- data.frame(moderator = integer(0), value = numeric(0))"
    ws = [f"w{s}" for s in model.tags]
    counts = ", ".join(f"length({w}_at)" for w in ws)
    values = ", ".join(f"{w}_at + {w}_mean" for w in ws)
    return (
        f"moderator_values <- data.frame(moderator = rep(seq_len({len(ws)}), c({counts})),\n"
        f"                               value = c({values}))"
    )


def name(role: str, latent: set[str]) -> str:
    # Factors are upper case, observed variables lower case, as in the model syntax.
    return role.upper() if role in latent else role


def title(model: MediationModel) -> str:
    text = f"{model.x.label} to {model.y.label} through {model.m.label}"
    if model.moderators:
        text += f", moderated by {' and '.join(m.variable.label for m in model.moderators)}"
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
    x, m, y = (name(r, latent) for r in ("x", "m", "y"))
    # Observed scores interact through product columns, factors through modsem's colon.
    joined = model.package == MODSEM
    covariates = "".join(f" + cov{i}" for i in range(1, len(model.covariates) + 1))
    m_terms, y_terms = [f"a*{x}"], [f"c*{x}", f"b*{m}"]
    for s, moderator in zip(model.tags, model.moderators, strict=True):
        w, paths = name(f"w{s}", latent), set(moderator.paths)
        xw = f"{x}:{w}" if joined else f"xw{s}"
        mw = f"{m}:{w}" if joined else f"mw{s}"
        if "a" in paths:
            m_terms += [f"a_w{s}*{w}", f"a_xw{s}*{xw}"]
        if paths & {"b", "c"}:
            y_terms.append(f"y_w{s}*{w}")
        if "b" in paths:
            y_terms.append(f"b_mw{s}*{mw}")
        if "c" in paths:
            y_terms.append(f"c_xw{s}*{xw}")
    return [f"{m} ~ {' + '.join(m_terms)}{covariates}", f"{y} ~ {' + '.join(y_terms)}{covariates}"]


def model_lines(model: MediationModel, structure: list[str], base: str = "") -> list[str]:
    parts = [base] if base else [r_string(s) for s in structure]
    parts += definition_lines(model)
    return ["model <- paste(", *(f"  {p}," for p in parts), '  sep = "\\n"', ")"]


def centre_scores(model: MediationModel) -> str:
    ws = [f"w{s}" for s in model.tags]
    lines = [f"{w}_mean <- mean(med${w})" for w in ws]
    names = ", ".join(f'"{v}"' for v in ("x", "m", *ws))
    lines += [
        "# Centred, so each path is its effect where the other variables are at their means.",
        f"for (v in c({names})) med[[v]] <- med[[v]] - mean(med[[v]])",
    ]
    for w in ws:
        lines += [f"med$x{w} <- med$x * med${w}", f"med$m{w} <- med$m * med${w}"]
    return "\n".join(lines)


def lavaan_lines(
    model: MediationModel, structure: list[str], latent: set[str], booted: bool, workers: int
) -> list[str]:
    lines = []
    if model.moderators:
        lines.append(centre_scores(model))
        lines += [OBSERVED_NOTE, *(OBSERVED_AT.format(w=f"w{s}") for s in model.tags)]
        lines.append(AT)
    lines += model_lines(model, structure)
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
    observed = [s for k, s in enumerate(model.tags) if not model.latent(k)]
    factors = [s for k, s in enumerate(model.tags) if model.latent(k)]
    lines += [CENTRE_W.format(w=f"w{s}") for s in observed]
    if factors:
        lines.append(FIRST_FIT.format(method=model.method))
        lines += [LATENT_AT.format(w=f"w{s}", factor=f"W{s}") for s in factors]
    if observed:
        lines += [OBSERVED_NOTE, *(OBSERVED_AT.format(w=f"w{s}") for s in observed)]
    lines += [AT, *model_lines(model, structure, base="base")]
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


def definition_lines(model: MediationModel) -> list[str]:
    # R expressions that give the syntax of the defined effects.
    if not model.moderated:
        return [r_string("indirect := a*b"), r_string("total := c + a*b")]
    tags = model.tags
    lines = []
    for kind in ("indirect", "direct"):
        which = depends(model, kind)
        if not which:
            if kind == "indirect":
                lines.append(r_string("indirect := a*b"))
            continue
        # sprintf's arguments: each moderator's place among its values, then the values.
        place = {k: f"%{len(which) + p + 1}$s" for p, k in enumerate(which)}

        def path(symbol: str, term: str, on: list[int], place=place) -> str:
            terms = [f"{term}{tags[k]}*{place[k]}" for k in on if k in place]
            return f"({symbol} + {' + '.join(terms)})" if terms else symbol

        if len(model.moderators) == 1:
            label = f"{kind}_%1$d"
        else:
            label = f"{kind}_" + "_".join(f"w{k + 1}_%{p + 1}$d" for p, k in enumerate(which))
        if kind == "indirect":
            effect = f"{path('a', 'a_xw', model.on('a'))}*{path('b', 'b_mw', model.on('b'))}"
        else:
            effect = path("c", "c_xw", model.on("c"))[1:-1]
        values = ", ".join(f"w{tags[k]}_at" for k in which)
        lines.append(f"at({r_string(f'{label} := {effect}')}, {values})")
    for k in indexed(model):
        product = f"a_xw{tags[k]}*b" if k in model.on("a") else f"a*b_mw{tags[k]}"
        lines.append(r_string(f"{index_label(model, k)} := {product}"))
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
