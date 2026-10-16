import contextlib
import io
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from labcatalog.pipeline import CatalogResult
from labcatalog.reports.codegen import number
from labcatalog.stats import analysis
from labcatalog.stats.analysis import CHOICE, ITEM_PREFIX, item_key, item_variable
from labcatalog.stats.analysis_script import (
    PYTHON,
    R,
    abbreviation,
    demographic_items,
    item_label,
    none,
    other_numbers,
    r_string,
)
from labcatalog.stats.cfa import is_total
from labcatalog.stats.rbridge import MULTILEVEL_PACKAGES as PACKAGES
from labcatalog.stats.rbridge import install_command, package_check, run_r
from labcatalog.stats.summary import wave_order

DATA_FILE = "multilevel_data.csv"
PERSON = "id"
TIME = "time"
WAVE = "wave"
INTERCEPT = "(Intercept)"
RESIDUAL = "Residual"
SINGULAR = "singular"
OUTPUTS = ("icc", "fixed", "random", "fit_stats", "notes")
PERSON_MEAN = ", person mean"
DEVIATION = ", deviation from the person mean"

R_HEADER = """\
# Multilevel model for {project}, written by labcatalog.
# d is the data saved beside this script: one row per person and wave, with time counting
# the study's waves from the first one chosen (0, 1, 2, ...; a skipped wave leaves a gap) and
# scores as labcatalog computed them.
# Needs the R packages {names}; install them once with: {install}
d <- read.csv({path}, check.names = FALSE)
"""
PYTHON_HEADER = """\
# Multilevel model for {project}, written by labcatalog.
# d is the data saved beside this script: one row per person and wave, with time counting
# the study's waves from the first one chosen (0, 1, 2, ...; a skipped wave leaves a gap) and
# scores as labcatalog computed them.
# Needs pandas and statsmodels (pip install statsmodels).
import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

d = pd.read_csv({path})
"""
R_MODEL = """\
# {title}
# Fitted by REML with lme4; fixed effects tested with Satterthwaite df (lmerTest), as in JASP's
# linear mixed models, with Wald 95% CIs. Answer options are factors with the first option
# with data as the reference. Rows missing any variable of the model are left out.
{factors}used <- c({used})
before <- nrow(d)
d <- droplevels(d[complete.cases(d[, used]), ])
null_model <- lmerTest::lmer({y} ~ 1 + {null_random}, data = d, REML = TRUE)
icc <- performance::icc(null_model, by_group = TRUE)
print(icc)
fit <- lmerTest::lmer({y} ~ {fixed} + {random}, data = d, REML = TRUE)
print(summary(fit))
bounds <- confint(fit, parm = "beta_", method = "Wald")
print(bounds)
"""
R_FOOTER = """\
icc <- data.frame(level = icc$Group, icc = icc$ICC)
coefs <- summary(fit)$coefficients
fixed <- data.frame(term = rownames(coefs), estimate = coefs[, 1], se = coefs[, 2],
                    df = coefs[, 3], statistic = coefs[, 4], p = coefs[, 5],
                    low = bounds[, 1], high = bounds[, 2])
parts <- as.data.frame(lme4::VarCorr(fit))
parts$grp <- sub("[.][0-9]+$", "", parts$grp)
variances <- parts[is.na(parts$var2), ]
random <- data.frame(level = variances$grp, term = ifelse(is.na(variances$var1), "", variances$var1),
                     variance = variances$vcov, sd = variances$sdcor, correlation = NA)
for (i in which(!is.na(parts$var2))) {
  random$correlation[random$level == parts$grp[i] & random$term == parts$var2[i]] <- parts$sdcor[i]
}
fit_stats <- data.frame(observations = nrow(d), people = length(unique(d[[PERSON_COLUMN]])),
                        groups = GROUPS, dropped = before - nrow(d),
                        reml_criterion = lme4::REMLcrit(fit),
                        log_likelihood = as.numeric(logLik(fit)), aic = AIC(fit), bic = BIC(fit))
notes <- data.frame(note = as.character(c(if (lme4::isSingular(fit)) "singular",
                                          fit@optinfo$conv$lme4$messages)))
"""
PYTHON_MODEL = """\
# {title}
# Fitted by REML with statsmodels (MixedLM), with Wald 95% CIs; statsmodels has no
# Satterthwaite df, so p values come from z. Answer options are categories with the first
# option with data as the reference. Rows missing any variable of the model are left out.
{factors}used = [{used}]
before = len(d)
d = d.dropna(subset=used).copy()
{unused}

def mixed(formula, re_formula, vc_formula):
    model = smf.mixedlm(formula, d, groups=d[{top}], re_formula=re_formula,
                        vc_formula=vc_formula)
    # No one optimizer reaches lme4's optimum on every model, so keep the best of three.
    best, notes = None, []
    for method in ("lbfgs", "bfgs", "powell"):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                result = model.fit(reml=True, method=method)
            except np.linalg.LinAlgError:
                continue
        if best is None or result.llf > best.llf:
            best, notes = result, [str(w.message) for w in caught]
    return best, list(dict.fromkeys(notes))


def variances(result):
    # Each random effect's variance, then the residual's.
    found = []
    cov = result.cov_re
    names = [{intercept} if name == "Group" else name for name in cov.index]
    for i, name in enumerate(names):
        correlation = np.nan
        if i > 0:
            correlation = cov.iloc[i, 0] / np.sqrt(cov.iloc[i, i] * cov.iloc[0, 0])
        found.append(dict(level={top}, term=name, variance=cov.iloc[i, i],
                          sd=np.sqrt(cov.iloc[i, i]), correlation=correlation))
    terms = {vc_terms}
    for name, value in zip(result.model.exog_vc.names, result.vcomp):
        found.append(dict(level={person}, term=terms[name], variance=value, sd=np.sqrt(value),
                          correlation=np.nan))
    found.append(dict(level="Residual", term="", variance=result.scale,
                      sd=np.sqrt(result.scale), correlation=np.nan))
    return pd.DataFrame(found)


null_model, _ = mixed("{y} ~ 1", "~1", {null_vc})
null_parts = variances(null_model)
levels = null_parts[null_parts["level"] != "Residual"]
icc = pd.DataFrame(dict(level=levels["level"],
                        icc=levels["variance"] / null_parts["variance"].sum()))
print(icc)
fit, caught = mixed("{y} ~ {fixed}", "{re}", {vc})
print(fit.summary())
bounds = fit.conf_int().loc[fit.fe_params.index]
print(bounds)
"""
PYTHON_FOOTER = """\
fe = fit.fe_params.index
fixed = pd.DataFrame(dict(term=fe, estimate=fit.fe_params.values, se=fit.bse_fe.values,
                          df=np.nan, statistic=fit.tvalues[fe].values, p=fit.pvalues[fe].values,
                          low=bounds[0].values, high=bounds[1].values))
random = variances(fit)
fit_stats = pd.DataFrame([dict(observations=len(d), people=d[PERSON_COLUMN].nunique(),
                               groups=GROUPS, dropped=before - len(d),
                               reml_criterion=-2 * fit.llf, log_likelihood=fit.llf,
                               aic=np.nan, bic=np.nan)])
small = random["level"].ne("Residual") & (random["sd"] < 1e-4 * np.sqrt(fit.scale))
notes = pd.DataFrame(dict(note=(["singular"] if small.any() else [])
                          + ([] if fit.converged else ["did not converge"]) + caught))
"""


@dataclass
class Model:
    outcome: str
    datasets: list[str]
    covariates: list[str] = field(default_factory=list)
    by_person: bool = True
    by_group: bool = False
    slope: bool = True
    # Each-wave number covariates as each person's mean and the wave's deviation from it.
    split: bool = False


@dataclass
class Source:
    by_id: pd.Series
    by_link: pd.Series


@dataclass
class Covariate:
    key: str
    label: str
    column: str
    # Answer options as (value, label); empty for numbers and scores.
    levels: list[tuple[float, str]]
    # The files it comes from, by wave; one value for every wave sits under None.
    sources: dict[str | None, list[Source]]

    def lookup(self, people: np.ndarray, links: np.ndarray, wave: str) -> np.ndarray:
        found = self.sources.get(None) or self.sources.get(wave, [])
        values = np.full(len(people), np.nan)
        done = np.zeros(len(people), dtype=bool)
        # Matched by ID when a file has the person, otherwise the way stats.correlate_by says.
        for source in found:
            hit = ~done & np.isin(people, source.by_id.index)
            values[hit] = source.by_id.reindex(people[hit]).to_numpy()
            done |= hit
        for source in found:
            hit = ~done & (source.by_link.index.get_indexer(links) >= 0)
            values[hit] = source.by_link.reindex(links[hit]).to_numpy()
            done |= hit
        return values


@dataclass
class Long:
    frame: pd.DataFrame
    outcome: str
    group: str | None
    covariates: list[Covariate]
    # Rows whose ID is missing or repeats within its file.
    left_out: int


@dataclass
class Term:
    label: str
    estimate: float
    se: float
    df: float | None
    statistic: float
    p: float
    low: float
    high: float


@dataclass
class Variance:
    level: str
    term: str
    variance: float
    sd: float
    correlation: float | None


@dataclass
class Fitted:
    engine: str
    icc: list[tuple[str, float]]
    fixed: list[Term]
    random: list[Variance]
    observations: int
    people: int
    groups: int | None
    dropped: int
    left_out: int
    reml_criterion: float
    log_likelihood: float
    aic: float | None
    bic: float | None
    singular: bool
    notes: list[str]


def group_name(result: CatalogResult) -> str | None:
    group = result.project.config.ids.group
    return None if group is None else group.name


def loaded_names(result: CatalogResult) -> list[str]:
    return [d.name for d in result.project.config.datasets if d.name in result.datasets]


def outcome_choices(result: CatalogResult) -> dict[str, str]:
    found: dict[str, str] = {}
    for s in result.catalog.scores:
        instrument = result.project.instruments[s.instrument_id]
        found.setdefault(f"{s.instrument_id}.{s.score_id}", f"{abbreviation(instrument)} {s.label}")
    for v in analysis.number_items(result, loaded_names(result)):
        found.setdefault(f"{ITEM_PREFIX}{v.instrument_id}.{v.item_id}", item_label(result, v))
    return found


def occasions(result: CatalogResult, outcome: str) -> list[str]:
    configs = {d.name: d for d in result.project.config.datasets}
    if outcome.startswith(ITEM_PREFIX):
        keys = [item_key(v) for v in analysis.number_items(result, loaded_names(result))]
    else:
        keys = [s.key for s in result.catalog.scores]
    names = [k.rsplit("@", 1)[1] for k in keys if k.rsplit("@", 1)[0] == outcome]
    return sorted(names, key=lambda n: (configs[n].study, wave_order(configs[n].wave), n))


def default_model(result: CatalogResult, choices: list[str] | None = None) -> Model | None:
    # The first total measured at two or more waves, among the outcomes offered.
    choices = list(outcome_choices(result)) if choices is None else choices
    if not choices:
        return None
    instruments = result.project.instruments

    def repeated_total(key: str) -> bool:
        if key.startswith(ITEM_PREFIX):
            return False
        instrument_id, score_id = key.split(".", 1)
        return is_total(instruments[instrument_id], score_id) and len(occasions(result, key)) > 1

    outcome = next((k for k in choices if repeated_total(k)), choices[0])
    configs = {d.name: d for d in result.project.config.datasets}
    names = occasions(result, outcome)
    study = configs[names[0]].study
    return Model(outcome, [n for n in names if configs[n].study == study])


def covariate_keys(result: CatalogResult) -> list[str]:
    names = loaded_names(result)
    items = demographic_items(result, names) + other_numbers(result, names)
    return [item_key(v) for v in items] + [s.key for s in result.catalog.scores]


def variable_label(result: CatalogResult, key: str) -> str:
    if key.startswith(ITEM_PREFIX):
        return item_label(result, item_variable(result, key))
    score = next(s for s in result.catalog.scores if s.key == key)
    return f"{abbreviation(result.project.instruments[score.instrument_id])} {score.label}"


def each_wave(key: str) -> bool:
    # A covariate key without a dataset takes each wave's own value.
    return "@" not in key


def covariate_choices(result: CatalogResult, labels: dict[str, str]) -> dict[str, str]:
    configs = {d.name: d for d in result.project.config.datasets}
    keys = covariate_keys(result)
    found = {k: f"{variable_label(result, k)} ({labels[k.rsplit('@', 1)[1]]})" for k in keys}
    first: dict[str, str] = {}
    waves: dict[str, set[tuple[str, str]]] = {}
    for key in keys:
        base, name = key.rsplit("@", 1)
        first.setdefault(base, key)
        waves.setdefault(base, set()).add((configs[name].study, configs[name].wave))
    for base, held in waves.items():
        # Offered when one study measures it in two or more waves.
        studies = [study for study, _ in held]
        if len(studies) > len(set(studies)):
            found[base] = f"{variable_label(result, first[base])} (each wave)"
    return found


def keys_of(keys: list[str], base: str) -> list[str]:
    return [k.rsplit("@", 1)[1] for k in keys if k.rsplit("@", 1)[0] == base]


def holders(result: CatalogResult, base: str, study: str) -> list[str]:
    configs = {d.name: d for d in result.project.config.datasets}
    return [n for n in keys_of(covariate_keys(result), base) if configs[n].study == study]


def problem(result: CatalogResult, model: Model) -> str | None:
    configs = {d.name: d for d in result.project.config.datasets}
    if not model.datasets:
        return "Choose at least one wave."
    if len({configs[n].study for n in model.datasets}) > 1:
        return "Choose waves from one study."
    if len({configs[n].wave for n in model.datasets}) < len(model.datasets):
        return "Choose one dataset per wave."
    if not (model.by_person or model.by_group):
        return "Choose at least one level: people or groups."
    if model.by_person and len(model.datasets) < 2:
        return "People need two or more waves; choose more waves, or groups only."
    if model.by_group:
        if group_name(result) is None:
            return "Name a group under ids in labcatalog.yaml to model groups."
        missing = [n for n in model.datasets if result.datasets[n].group is None]
        if missing:
            return f"{', '.join(missing)} has no group column."
    study = configs[model.datasets[0]].study
    for key in filter(each_wave, model.covariates):
        held = holders(result, key, study)
        missing = [
            configs[n].wave
            for n in model.datasets
            if configs[n].wave not in {configs[h].wave for h in held}
        ]
        if missing:
            label = variable_label(result, f"{key}@{held[0]}") if held else key
            return f"{label} is not measured in wave {', '.join(missing)}."
    return None


def long_frame(result: CatalogResult, model: Model) -> Long:
    configs = {d.name: d for d in result.project.config.datasets}
    ordered = sorted(model.datasets, key=lambda n: wave_order(configs[n].wave))
    outcome = identifier(model.outcome.split(".", 1)[1], {PERSON, TIME, WAVE})
    group = group_name(result) if model.by_group else None
    taken = {PERSON, TIME, WAVE, outcome, *([group] if group else [])}
    study = configs[ordered[0]].study
    covariates = [covariate(result, key, taken, study) for key in model.covariates]
    # Time counts the study's waves, so a skipped wave leaves a gap.
    waves = sorted({d.wave for d in configs.values() if d.study == study}, key=wave_order)
    first = waves.index(configs[ordered[0]].wave)
    parts, left_out = [], 0
    for name in ordered:
        time = waves.index(configs[name].wave) - first
        loaded = result.datasets[name]
        ids = loaded.frame[loaded.id_column].astype("string")
        keep = analysis.linkable(ids)
        left_out += int((~keep).sum())
        people = ids.to_numpy()[keep]
        part = pd.DataFrame({PERSON: people, WAVE: configs[name].wave, TIME: time})
        if group:
            part[group] = loaded.group.astype("string").to_numpy()[keep]
        part[outcome] = analysis.row_values(result, f"{model.outcome}@{name}")[keep]
        links = analysis.link_keys(result, name).to_numpy()[keep]
        for c in covariates:
            part[c.column] = c.lookup(people, links, configs[name].wave)
        parts.append(part)
    frame = pd.concat(parts, ignore_index=True)
    if model.split:
        frame, covariates = split_within(frame, covariates, taken)
    return Long(frame, outcome, group, covariates, left_out)


def splittable(c: Covariate) -> bool:
    return None not in c.sources and not c.levels


def split_within(
    frame: pd.DataFrame, covariates: list[Covariate], taken: set[str]
) -> tuple[pd.DataFrame, list[Covariate]]:
    # Between people: the person's mean over the waves; within: each wave minus that mean.
    found = []
    for c in covariates:
        if not splittable(c):
            found.append(c)
            continue
        mean = frame.groupby(PERSON)[c.column].transform("mean")
        between = replace(
            c, column=identifier(f"{c.column}_mean", taken), label=f"{c.label}{PERSON_MEAN}"
        )
        taken.add(between.column)
        within = replace(
            c, column=identifier(f"{c.column}_within", taken), label=f"{c.label}{DEVIATION}"
        )
        taken.add(within.column)
        position = frame.columns.get_loc(c.column)
        values = frame.pop(c.column)
        frame.insert(position, within.column, values - mean)
        frame.insert(position, between.column, mean)
        found += [between, within]
    return frame, found


def covariate(result: CatalogResult, key: str, taken: set[str], study: str) -> Covariate:
    configs = {d.name: d for d in result.project.config.datasets}
    timed = each_wave(key)
    names = holders(result, key, study) if timed else [key.rsplit("@", 1)[1]]
    first = f"{key}@{names[0]}" if timed else key
    label = variable_label(result, first) + (" (each wave)" if timed else "")
    if key.startswith(ITEM_PREFIX):
        variable = item_variable(result, first)
        column = variable.item_id if timed else variable.column
        levels = (
            [(float(o.value), o.label) for o in variable.response_options]
            if variable.type == CHOICE
            else []
        )
    else:
        score_id = first.rsplit("@", 1)[0].split(".", 1)[1]
        column = score_id if timed else f"{score_id}_{names[0]}"
        levels = []
    column = identifier(column, taken)
    taken.add(column)
    sources: dict[str | None, list[Source]] = {}
    for name in names:
        wave = configs[name].wave if timed else None
        sources.setdefault(wave, []).append(source(result, f"{key}@{name}" if timed else key))
    return Covariate(key=key, label=label, column=column, levels=levels, sources=sources)


def source(result: CatalogResult, key: str) -> Source:
    dataset = key.rsplit("@", 1)[1]
    values = analysis.row_values(result, key)
    loaded = result.datasets[dataset]
    ids = loaded.frame[loaded.id_column].astype("string")
    own = analysis.linkable(ids)
    links = analysis.link_keys(result, dataset)
    linked = analysis.linkable(links)
    return Source(
        by_id=pd.Series(values[own], index=ids.to_numpy()[own]),
        by_link=pd.Series(values[linked], index=links.to_numpy()[linked]),
    )


def identifier(name: str, taken: set[str]) -> str:
    # Plain names, so the formulas in both languages need no quoting.
    found = re.sub(r"\W", "_", name)
    found = f"x_{found}" if found[:1].isdigit() else found
    base, n = found, 2
    while found in taken:
        found, n = f"{base}_{n}", n + 1
    return found


def structure(model: Model, long: Long) -> dict[str, str]:
    timed = len(model.datasets) > 1
    slope = model.by_person and model.slope and timed
    fixed = [TIME] if timed else []
    fixed += [c.column for c in long.covariates]
    if model.by_person and long.group:
        null_random = f"(1 | {long.group}) + (1 | {PERSON})"
        random = null_random + (f" + (0 + {TIME} | {PERSON})" if slope else "")
        top, re_formula = long.group, "~1"
        null_vc = {PERSON: f"0 + C({PERSON})"}
        vc = null_vc | ({f"{PERSON}_{TIME}": f"0 + C({PERSON}):{TIME}"} if slope else {})
    elif model.by_person:
        null_random = f"(1 | {PERSON})"
        random = f"(1 + {TIME} | {PERSON})" if slope else null_random
        top, re_formula, null_vc, vc = PERSON, f"~{TIME}" if slope else "~1", {}, {}
    else:
        null_random = random = f"(1 | {long.group})"
        top, re_formula, null_vc, vc = long.group, "~1", {}, {}
    return {
        "fixed": " + ".join(fixed) or "1",
        "random": random,
        "null_random": null_random,
        "top": top,
        "re": re_formula,
        "vc": python_dict(vc),
        "null_vc": python_dict(null_vc),
        "used": [
            long.outcome,
            *fixed,
            *([PERSON] if model.by_person else []),
            *([long.group] if long.group else []),
        ],
    }


def python_dict(found: dict[str, str]) -> str:
    return (
        "{" + ", ".join(f"{r_string(k)}: {r_string(v)}" for k, v in found.items()) + "}"
        if found
        else "None"
    )


def title(model: Model, long: Long, label: str) -> str:
    levels = [
        *(["waves within people"] if model.by_person else []),
        *([f"people within each {long.group}"] if long.group else []),
    ]
    slope = model.by_person and model.slope and len(model.datasets) > 1
    random = " with a random slope of time for each person" if slope else ""
    return f"Multilevel model of {label}: {' and '.join(levels)}{random}."


def code(model: Model, long: Long, label: str) -> tuple[str, str]:
    parts = structure(model, long)
    used = ", ".join(r_string(name) for name in parts["used"])
    factors = [c for c in long.covariates if c.levels]
    r_factors = "".join(
        f"d[[{r_string(c.column)}]] <- factor(d[[{r_string(c.column)}]], "
        f"levels = c({', '.join(number(v) for v, _ in c.levels)}), "
        f"labels = c({', '.join(r_string(t) for _, t in c.levels)}))\n"
        for c in factors
    )
    python_factors = "".join(
        f"d[{r_string(c.column)}] = pd.Categorical(d[{r_string(c.column)}].map("
        f"{{{', '.join(f'{number(v)}: {r_string(t)}' for v, t in c.levels)}}}), "
        f"categories=[{', '.join(r_string(t) for _, t in c.levels)}])\n"
        for c in factors
    )
    unused = "".join(
        f"d[{r_string(c.column)}] = d[{r_string(c.column)}].cat.remove_unused_categories()\n"
        for c in factors
    )
    heading = title(model, long, label)
    r = R_MODEL.format(
        title=heading,
        factors=r_factors,
        used=used,
        y=long.outcome,
        fixed=parts["fixed"],
        random=parts["random"],
        null_random=parts["null_random"],
    )
    terms = {PERSON: INTERCEPT, f"{PERSON}_{TIME}": TIME}
    python = PYTHON_MODEL.format(
        title=heading,
        factors=python_factors,
        used=used,
        unused=unused,
        y=long.outcome,
        fixed=parts["fixed"],
        re=parts["re"],
        vc=parts["vc"],
        null_vc=parts["null_vc"],
        top=r_string(parts["top"]),
        person=r_string(PERSON),
        intercept=r_string(INTERCEPT),
        vc_terms=python_dict(terms),
    )
    return r, python


def footers(long: Long) -> tuple[str, str]:
    groups_r = f"length(unique(d[[{r_string(long.group)}]]))" if long.group else "NA"
    groups_py = f"d[{r_string(long.group)}].nunique()" if long.group else "np.nan"
    r = R_FOOTER.replace("PERSON_COLUMN", r_string(PERSON)).replace("GROUPS", groups_r)
    python = PYTHON_FOOTER.replace("PERSON_COLUMN", r_string(PERSON)).replace("GROUPS", groups_py)
    return r, python


def headers(result: CatalogResult, path: str) -> tuple[str, str]:
    project = result.project.config.project.name
    return (
        R_HEADER.format(
            project=project,
            names=", ".join(PACKAGES),
            install=install_command(PACKAGES),
            path=r_string(path),
        ),
        PYTHON_HEADER.format(project=project, path=r_string(path)),
    )


def scripts(result: CatalogResult, model: Model, long: Long, label: str) -> tuple[str, str]:
    r_head, py_head = headers(result, DATA_FILE)
    r, python = code(model, long, label)
    return f"{r_head}\n{r}", f"{py_head}\n{python}"


def run(result: CatalogResult, model: Model, long: Long, label: str, rscript: str | None) -> Fitted:
    # R when the Settings page names an Rscript, otherwise the Python version, run here.
    r, python = code(model, long, label)
    r_footer, python_footer = footers(long)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        long.frame.to_csv(folder / DATA_FILE, index=False)
        r_head, py_head = headers(result, (folder / DATA_FILE).as_posix())
        if rscript:
            writes = [
                f"write.csv({name}, {r_string((folder / f'{name}.csv').as_posix())}, "
                "row.names = FALSE)"
                for name in OUTPUTS
            ]
            path = folder / "multilevel.R"
            text = "\n".join([package_check(PACKAGES), r_head, r, r_footer, *writes])
            path.write_text(text, encoding="utf-8")
            run_r(rscript, [str(path)])
            found = {n: pd.read_csv(folder / f"{n}.csv") for n in OUTPUTS}
            return read(found, long, R)
        names: dict = {}
        with contextlib.redirect_stdout(io.StringIO()):
            exec("\n".join([py_head, python, python_footer]), names)
        return read({n: names[n] for n in OUTPUTS}, long, PYTHON)


def read(found: dict[str, pd.DataFrame], long: Long, engine: str) -> Fitted:
    stats = found["fit_stats"].iloc[0]
    notes = [str(n) for n in found["notes"]["note"].dropna()]
    return Fitted(
        engine=engine,
        icc=sorted(
            ((level_label(row.level, long), float(row.icc)) for row in found["icc"].itertuples()),
            key=lambda pair: level_order(pair[0]),
        ),
        fixed=sorted(
            (
                Term(
                    label=term_label(str(row.term), long),
                    estimate=float(row.estimate),
                    se=float(row.se),
                    df=none(row.df),
                    statistic=float(row.statistic),
                    p=float(row.p),
                    low=float(row.low),
                    high=float(row.high),
                )
                for row in found["fixed"].itertuples()
            ),
            key=lambda t: term_order(t.label, long),
        ),
        random=sorted(
            (
                Variance(
                    level=level_label(row.level, long),
                    term=term_label(str(row.term) if pd.notna(row.term) else "", long),
                    variance=float(row.variance),
                    sd=float(row.sd),
                    correlation=none(row.correlation),
                )
                for row in found["random"].itertuples()
            ),
            key=lambda v: (level_order(v.level), v.term != "Intercept"),
        ),
        observations=int(stats["observations"]),
        people=int(stats["people"]),
        groups=None if pd.isna(stats["groups"]) else int(stats["groups"]),
        dropped=int(stats["dropped"]),
        left_out=long.left_out,
        reml_criterion=float(stats["reml_criterion"]),
        log_likelihood=float(stats["log_likelihood"]),
        aic=none(stats["aic"]),
        bic=none(stats["bic"]),
        singular=SINGULAR in notes,
        notes=[n for n in notes if n != SINGULAR],
    )


def term_order(label: str, long: Long) -> int:
    # Formula order: intercept, time, then the covariates as chosen.
    labels = ["Intercept", "Time (waves since the first)", *(c.label for c in long.covariates)]
    return next(
        (n for n, name in enumerate(labels) if label == name or label.startswith(f"{name}: ")),
        len(labels),
    )


def level_order(label: str) -> int:
    # Groups, then people, then the residual.
    return {"Person": 1, RESIDUAL: 2}.get(label, 0)


def level_label(level: str, long: Long) -> str:
    if level == PERSON:
        return "Person"
    if level == RESIDUAL:
        return RESIDUAL
    return level.capitalize()


def term_label(term: str, long: Long) -> str:
    if term in (INTERCEPT, "Intercept", "Group"):
        return "Intercept"
    if term == TIME:
        return "Time (waves since the first)"
    for c in long.covariates:
        if term == c.column:
            return c.label
        for _, level in c.levels:
            if term in (f"{c.column}{level}", f"{c.column}[T.{level}]"):
                return f"{c.label}: {level}"
    return term


def references(long: Long) -> list[tuple[str, str]]:
    # The level each answer-option covariate is compared with: the first one with data.
    found = []
    used = long.frame.dropna()
    for c in long.covariates:
        present = [label for value, label in c.levels if (used[c.column] == value).any()]
        if present:
            found.append((c.label, present[0]))
    return found
