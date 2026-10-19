import contextlib
import io
import re
import tempfile
import textwrap
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np
import pandas as pd

from labcatalog.pipeline import CatalogResult
from labcatalog.reports.codegen import number
from labcatalog.stats import analysis, imputation
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
TIME_LABEL = "Time (waves since the first)"
WAVES = "wave"
# Days in each unit time can count besides waves.
DAYS = {"month": 365.25 / 12, "year": 365.25}
RESIDUAL = "Residual"
SINGULAR = "singular"
OUTPUTS = ("icc", "fixed", "random", "fit_stats", "notes")
PERSON_MEAN = ", person mean"
DEVIATION = ", deviation from the person mean"

R_HEADER = """\
# Multilevel model for {project}, written by labcatalog.
# d is the data saved beside this script: one row per person and wave, with time as the
# model's title below says and scores as labcatalog computed them.
# Needs the R packages {names}; install them once with: {install}
d <- read.csv({path}, check.names = FALSE)
"""
PYTHON_HEADER = """\
# Multilevel model for {project}, written by labcatalog.
# d is the data saved beside this script: one row per person and wave, with time as the
# model's title below says and scores as labcatalog computed them.
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
R_RANDOM = """\
random_of <- function(fit) {
  parts <- as.data.frame(lme4::VarCorr(fit))
  parts$grp <- sub("[.][0-9]+$", "", parts$grp)
  variances <- parts[is.na(parts$var2), ]
  random <- data.frame(level = variances$grp,
                       term = ifelse(is.na(variances$var1), "", variances$var1),
                       variance = variances$vcov, sd = variances$sdcor, correlation = NA)
  for (i in which(!is.na(parts$var2))) {
    random$correlation[random$level == parts$grp[i] & random$term == parts$var2[i]] <-
      parts$sdcor[i]
  }
  random
}
"""
R_FOOTER = """\
icc <- data.frame(level = icc$Group, icc = icc$ICC)
coefs <- summary(fit)$coefficients
fixed <- data.frame(term = rownames(coefs), estimate = coefs[, 1], se = coefs[, 2],
                    df = coefs[, 3], statistic = coefs[, 4], p = coefs[, 5],
                    low = bounds[, 1], high = bounds[, 2])
random <- random_of(fit)
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
R_IMPUTE = """\
# Multiple imputation with mice of the covariates where they are missing: {m} imputed data sets
# by predictive mean matching (answer options as categories), seed {seed}{by_study}. Each person
# is one row with each wave's values side by side, so their outcomes and other waves predict
# them{grouped}. Outcomes are not imputed: the mixed model already uses every wave a person has.
# Each column is predicted by those that correlate at least {mincor} with it or with its
# missingness (quickpred). The imputation is kept in the file below, named after the data and
# these choices, and read again; delete the file to impute again.
imputation_file <- {file}
person_columns <- c({person_columns})
wave_columns <- c({wave_columns})
factor_columns <- c({factor_columns})
people <- unique(d[[{person}]])
waves <- unique(d[[{wave}]])
first_value <- function(v) v[!is.na(v)][match(people, d[[{person}]][!is.na(v)])]
wide <- data.frame(row.names = seq_along(people))
for (column in person_columns) wide[[column]] <- first_value(d[[column]])
for (k in seq_along(waves)) {{
  rows <- d[[{wave}]] == waves[k]
  for (column in c({outcome}, wave_columns)) {{
    wide[[paste0(column, "_w", k)]] <- d[[column]][rows][match(people, d[[{person}]][rows])]
  }}
}}
answers <- c(intersect(person_columns, factor_columns),
             paste0(rep(intersect(wave_columns, factor_columns), each = length(waves)), "_w",
                    seq_along(waves)))
{blocks}
impute <- function(part) {{
  part <- part[colSums(!is.na(part)) > 0]
  categories <- intersect(answers, names(part))
  part[categories] <- lapply(part[categories], factor)
  mice::mice(part, m = {m}, seed = {seed}, predictorMatrix = mice::quickpred(part, mincor = {mincor}),
             printFlag = FALSE)
}}
if (!file.exists(imputation_file)) {{
  saveRDS(lapply(blocks, function(rows) impute(wide[rows, , drop = FALSE])), imputation_file)
}}
imputation <- readRDS(imputation_file)
# Each imputed data set: the rows as they were with the covariates filled in{split}.
completed <- lapply(seq_len({m}), function(i) {{
  filled <- wide
  for (k in seq_along(blocks)) {{
    part <- mice::complete(imputation[[k]], i)
    part[] <- lapply(part, function(v) if (is.factor(v)) as.numeric(as.character(v)) else v)
    filled[blocks[[k]], names(part)] <- part
  }}
  x <- d
  person <- match(x[[{person}]], people)
  for (column in person_columns) x[[column]] <- filled[[column]][person]
  for (k in seq_along(waves)) {{
    rows <- x[[{wave}]] == waves[k]
    for (column in wave_columns) {{
      x[[column]][rows] <- filled[[paste0(column, "_w", k)]][person[rows]]
    }}
  }}
{splits}  x
}})
"""
R_POOLED_MODEL = """\
# {title}
# Fitted by REML with lme4 in each imputed data set and pooled with Rubin's rules
# (mitml::testEstimates), with Barnard and Rubin's df from each term's Satterthwaite df
# (lmerTest) averaged over the data sets, and 95% CIs from them. ICCs, variances and
# correlations are averaged over the data sets. Answer options are factors with the first option
# with data as the reference. Rows missing any variable of the model that is not imputed are
# left out.
used <- c({used})
before <- nrow(d)
average <- function(values) Reduce(`+`, values) / length(values)
fit_set <- function(d) {{
{factors}  d <- droplevels(d[complete.cases(d[, used]), ])
  list(d = d,
       null_model = lmerTest::lmer({y} ~ 1 + {null_random}, data = d, REML = TRUE),
       fit = lmerTest::lmer({y} ~ {fixed} + {random}, data = d, REML = TRUE))
}}
sets <- lapply(completed, fit_set)
fits <- lapply(sets, function(s) s$fit)
iccs <- lapply(sets, function(s) performance::icc(s$null_model, by_group = TRUE))
icc <- data.frame(level = iccs[[1]]$Group, icc = average(lapply(iccs, function(x) x$ICC)))
print(icc)
df_com <- average(lapply(fits, function(f) summary(f)$coefficients[, "df"]))
pooled <- mitml::testEstimates(fits, df.com = df_com)
print(pooled)
bounds <- confint(pooled)
print(bounds)
{random_of}randoms <- lapply(fits, random_of)
random <- randoms[[1]]
random$variance <- average(lapply(randoms, function(x) x$variance))
random$sd <- sqrt(random$variance)
random$correlation <- average(lapply(randoms, function(x) x$correlation))
print(random)
"""
R_POOLED_FOOTER = """\
coefs <- pooled$estimates
fixed <- data.frame(term = rownames(coefs), estimate = coefs[, "Estimate"],
                    se = coefs[, "Std.Error"], df = coefs[, "df"], statistic = coefs[, "t.value"],
                    p = coefs[, "P(>|t|)"], low = bounds[, 1], high = bounds[, 2])
# The rows each model used, the same in every imputed data set.
d <- sets[[1]]$d
fit_stats <- data.frame(observations = nrow(d), people = length(unique(d[[PERSON_COLUMN]])),
                        groups = GROUPS, dropped = before - nrow(d), reml_criterion = NA,
                        log_likelihood = NA, aic = NA, bic = NA, imputations = length(fits))
messages <- unique(unlist(lapply(fits, function(f) f@optinfo$conv$lme4$messages)))
notes <- data.frame(note = as.character(c(if (any(sapply(fits, lme4::isSingular))) "singular",
                                          messages)))
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
    # Waves, or months or years from the dates.
    time: str = WAVES


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
class Split:
    # An each-wave covariate as measured, and the person mean and deviation that replace it.
    column: str
    between: str
    within: str
    values: pd.Series


@dataclass
class Long:
    frame: pd.DataFrame
    outcome: str
    group: str | None
    covariates: list[Covariate]
    # Rows whose ID is missing or repeats within its file.
    left_out: int
    time_label: str = TIME_LABEL
    splits: list[Split] = field(default_factory=list)


@dataclass
class Imputing:
    m: int
    seed: int


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
    reml_criterion: float | None
    log_likelihood: float | None
    aic: float | None
    bic: float | None
    singular: bool
    notes: list[str]
    imputations: int | None = None


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
    return Model(outcome, wave_datasets(result, outcome))


def wave_datasets(result: CatalogResult, outcome: str, study: str | None = None) -> list[str]:
    # One dataset per wave of the first one's study, or of the study given, from its reporter.
    configs = {d.name: d for d in result.project.config.datasets}
    names = [n for n in occasions(result, outcome) if study in (None, configs[n].study)]
    if not names:
        return []
    first = configs[names[0]]
    found: dict[str, str] = {}
    for n in names:
        if configs[n].study == first.study and configs[n].reporter == first.reporter:
            found.setdefault(configs[n].wave, n)
    return list(found.values())


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


def covariate_choices(
    result: CatalogResult, labels: dict[str, str], datasets: list[str] | None = None
) -> dict[str, str]:
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
    if datasets and analysis.pooling(result, datasets):
        found = {k: v for k, v in found.items() if each_wave(k)}
        found |= pooled_covariates(result, analysis.studies_of(result, datasets))
    return found


def pooled_covariates(result: CatalogResult, studies: list[str]) -> dict[str, str]:
    # One file per study: each study's first file of the covariate together, then the second.
    configs = {d.name: d for d in result.project.config.datasets}
    by_base: dict[str, dict[str, list[str]]] = {}
    for key in covariate_keys(result):
        base, name = key.rsplit("@", 1)
        by_base.setdefault(base, {}).setdefault(configs[name].study, []).append(name)
    found = {}
    for base, held in by_base.items():
        if not all(s in held for s in studies):
            continue
        files = [sorted(held[s], key=lambda n: wave_order(configs[n].wave)) for s in studies]
        for paired in zip(*files, strict=False):
            label = variable_label(result, f"{base}@{paired[0]}")
            found[f"{base}@{analysis.POOL.join(paired)}"] = f"{label} ({' + '.join(paired)})"
    return found


def keys_of(keys: list[str], base: str) -> list[str]:
    return [k.rsplit("@", 1)[1] for k in keys if k.rsplit("@", 1)[0] == base]


def holders(result: CatalogResult, base: str, study: str) -> list[str]:
    configs = {d.name: d for d in result.project.config.datasets}
    return [n for n in keys_of(covariate_keys(result), base) if configs[n].study == study]


def study_model(result: CatalogResult, model: Model, study: str) -> Model:
    # One study's part of a pooled model, each pooled covariate taken from that study's file.
    configs = {d.name: d for d in result.project.config.datasets}

    def own(key: str) -> str:
        if each_wave(key):
            return key
        return next(
            analysis.part_key(key, n) for n in analysis.parts(key) if configs[n].study == study
        )

    return replace(
        model,
        datasets=[n for n in model.datasets if configs[n].study == study],
        covariates=[own(k) for k in model.covariates],
    )


def problem(result: CatalogResult, model: Model) -> str | None:
    configs = {d.name: d for d in result.project.config.datasets}
    if not model.datasets:
        return "Choose at least one wave."
    studies = analysis.studies_of(result, model.datasets)
    if len(studies) > 1:
        for study in studies:
            found = problem(result, study_model(result, model, study))
            if found:
                return f"{result.project.config.studies[study].label or study}: {found}"
        return None
    if len({configs[n].wave for n in model.datasets}) < len(model.datasets):
        return "Choose one dataset per wave."
    if not (model.by_person or model.by_group):
        return "Choose at least one level: people or groups."
    if model.by_person and len(model.datasets) < 2:
        return "People need two or more waves; choose more waves, or groups only."
    undated = [n for n in model.datasets if not configs[n].date_column]
    if model.time != WAVES and undated:
        return f"{', '.join(undated)} has no date_column, so time cannot count {model.time}s."
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
    studies = analysis.studies_of(result, model.datasets)
    if len(studies) > 1:
        return pooled_frame(result, model, studies)
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
    origin = None if model.time == WAVES else visit_dates(result, ordered[0]).min()
    parts, left_out = [], 0
    for name in ordered:
        loaded = result.datasets[name]
        ids = loaded.frame[loaded.id_column].astype("string")
        keep = analysis.linkable(ids)
        left_out += int((~keep).sum())
        people = ids.to_numpy()[keep]
        if origin is None:
            time = waves.index(configs[name].wave) - first
        else:
            time = ((visit_dates(result, name) - origin).dt.days / DAYS[model.time]).to_numpy()[
                keep
            ]
        part = pd.DataFrame({PERSON: people, WAVE: configs[name].wave, TIME: time})
        if group:
            part[group] = loaded.group.astype("string").to_numpy()[keep]
        part[outcome] = analysis.row_values(result, f"{model.outcome}@{name}")[keep]
        links = analysis.link_keys(result, name).to_numpy()[keep]
        for c in covariates:
            part[c.column] = c.lookup(people, links, configs[name].wave)
        parts.append(part)
    frame = pd.concat(parts, ignore_index=True)
    splits = []
    if model.split:
        frame, covariates, splits = split_within(frame, covariates, taken)
    label = TIME_LABEL
    if origin is not None:
        label = f"Time ({model.time}s since wave {configs[ordered[0]].wave} began)"
    return Long(frame, outcome, group, covariates, left_out, label, splits)


def pooled_frame(result: CatalogResult, model: Model, studies: list[str]) -> Long:
    # Each study's own rows, its people and groups kept apart, with the study as a fixed effect.
    longs = [long_frame(result, study_model(result, model, s)) for s in studies]
    first = longs[0]
    frames, waves = [], {}
    for code, (study, long) in enumerate(zip(studies, longs, strict=True), start=1):
        names = {c.column: f.column for c, f in zip(long.covariates, first.covariates, strict=True)}
        frame = long.frame.rename(columns=names)
        frame[PERSON] = study + "/" + frame[PERSON]
        if first.group:
            frame[first.group] = study + "/" + frame[first.group]
        # The nth chosen wave of each study shares one name, such as 1/baseline.
        position = {w: n for n, w in enumerate(dict.fromkeys(frame[WAVE]))}
        for wave, n in position.items():
            waves.setdefault(n, []).append(wave)
        frame[WAVE] = frame[WAVE].map(position)
        frame["_study"] = float(code)
        frames.append(frame)
    frame = pd.concat(frames, ignore_index=True)
    frame[WAVE] = frame[WAVE].map({n: "/".join(dict.fromkeys(w)) for n, w in waves.items()})
    column = identifier(analysis.STUDY_KEY, set(frame.columns))
    frame = frame.rename(columns={"_study": column})
    configs = result.project.config.studies
    study = Covariate(
        analysis.STUDY_KEY,
        "Study",
        column,
        [(float(n), configs[s].label or s) for n, s in enumerate(studies, start=1)],
        {},
    )
    label = first.time_label
    if label != TIME_LABEL:
        label = f"Time ({model.time}s since each study's first wave began)"
    left_out = sum(long.left_out for long in longs)
    # Each study's frame names its split covariates as the first study's does.
    splits = [
        replace(s, values=pd.concat([long.splits[n].values for long in longs], ignore_index=True))
        for n, s in enumerate(first.splits)
    ]
    covariates = [*first.covariates, study]
    return Long(frame, first.outcome, first.group, covariates, left_out, label, splits)


def pooled(long: Long) -> bool:
    return any(c.key == analysis.STUDY_KEY for c in long.covariates)


def visit_dates(result: CatalogResult, name: str) -> pd.Series:
    loaded = result.datasets[name]
    form = result.project.config.defaults.date_format
    return pd.to_datetime(loaded.frame[loaded.config.date_column], format=form, errors="coerce")


def splittable(c: Covariate) -> bool:
    return None not in c.sources and not c.levels


def split_within(
    frame: pd.DataFrame, covariates: list[Covariate], taken: set[str]
) -> tuple[pd.DataFrame, list[Covariate], list[Split]]:
    # Between people: the person's mean over the waves; within: each wave minus that mean.
    found, splits = [], []
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
        splits.append(Split(c.column, between.column, within.column, values))
    return frame, found, splits


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
    heading = f"Multilevel model of {label}: {' and '.join(levels)}{random}."
    if len(model.datasets) < 2:
        return heading
    first = "each study's first chosen wave" if pooled(long) else "the first chosen wave"
    if pooled(long):
        heading += " The studies' people and groups are their own, and the study is a fixed effect."
    if model.time == WAVES:
        return f"{heading} Time is waves since {first} (a skipped wave leaves a gap)."
    return f"{heading} Time is {model.time}s since the earliest visit date in {first}."


def r_factors(long: Long) -> str:
    return "".join(
        f"d[[{r_string(c.column)}]] <- factor(d[[{r_string(c.column)}]], "
        f"levels = c({', '.join(number(v) for v, _ in c.levels)}), "
        f"labels = c({', '.join(r_string(t) for _, t in c.levels)}))\n"
        for c in long.covariates
        if c.levels
    )


def code(model: Model, long: Long, label: str) -> tuple[str, str]:
    parts = structure(model, long)
    used = ", ".join(r_string(name) for name in parts["used"])
    factors = [c for c in long.covariates if c.levels]
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
        factors=r_factors(long),
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


def covariate_columns(long: Long) -> tuple[list[str], list[str], list[str]]:
    # The covariates as measured, before any split: one value per person, each wave's own, answers.
    split = {s.between: s.column for s in long.splits} | {s.within: s.column for s in long.splits}
    person, waves, factors = [], [], []
    for c in long.covariates:
        if c.key == analysis.STUDY_KEY:
            continue
        column = split.get(c.column, c.column)
        found = waves if each_wave(c.key) else person
        if column not in found:
            found.append(column)
        if c.levels:
            factors.append(column)
    return person, waves, factors


def imputed_rows(model: Model, long: Long) -> int:
    # Rows the model leaves out only for a missing covariate.
    covariates = [c.column for c in long.covariates]
    rest = [name for name in structure(model, long)["used"] if name not in covariates]
    frame = long.frame
    return int((frame[rest].notna().all(axis=1) & frame[covariates].isna().any(axis=1)).sum())


def data_frame(long: Long, imputing: bool) -> pd.DataFrame:
    # The imputation fills in each split covariate as measured, and splits it again.
    if not (imputing and long.splits):
        return long.frame
    return long.frame.assign(**{s.column: s.values for s in long.splits})


def imputation_plan(long: Long, imputing: Imputing) -> imputation.ImputationPlan:
    # Only names the kept imputation, after everything it reads.
    person, waves, factors = covariate_columns(long)
    study = [c.column for c in long.covariates if c.key == analysis.STUDY_KEY]
    numbers = [PERSON, WAVE, long.outcome, *study, *person, *waves]
    return imputation.ImputationPlan(
        imputing.m,
        imputing.seed,
        numbers=[n for n in numbers if n not in factors],
        factors=factors,
        by_study=pooled(long),
    )


def imputed_code(model: Model, long: Long, label: str, imputing: Imputing, file: str) -> str:
    person, waves, factors = covariate_columns(long)
    study = next((c.column for c in long.covariates if c.key == analysis.STUDY_KEY), None)
    blocks = (
        f"blocks <- split(seq_along(people), first_value(d[[{r_string(study)}]]))"
        if study
        else "blocks <- list(seq_along(people))"
    )
    person_id = r_string(PERSON)
    splits = "".join(
        f"  x[[{r_string(s.between)}]] <- ave(x[[{r_string(s.column)}]], x[[{person_id}]], "
        "FUN = function(v) mean(v, na.rm = TRUE))\n"
        f"  x[[{r_string(s.within)}]] <- x[[{r_string(s.column)}]] - x[[{r_string(s.between)}]]\n"
        for s in long.splits
    )
    impute = R_IMPUTE.format(
        m=imputing.m,
        seed=imputing.seed,
        by_study=", each study by itself" if study else "",
        grouped=f"; people of one {long.group} are imputed as if apart" if long.group else "",
        mincor=imputation.MIN_CORRELATION,
        file=r_string(file),
        person_columns=imputation.quoted(person),
        wave_columns=imputation.quoted(waves),
        factor_columns=imputation.quoted(factors),
        person=person_id,
        wave=r_string(WAVE),
        outcome=r_string(long.outcome),
        blocks=blocks,
        split="\n# and the split covariates split again" if long.splits else "",
        splits=splits,
    )
    parts = structure(model, long)
    fitted = R_POOLED_MODEL.format(
        title=title(model, long, label),
        used=", ".join(r_string(name) for name in parts["used"]),
        factors=textwrap.indent(r_factors(long), "  "),
        y=long.outcome,
        fixed=parts["fixed"],
        random=parts["random"],
        null_random=parts["null_random"],
        random_of=R_RANDOM,
    )
    return impute + fitted


def footers(long: Long, imputing: bool = False) -> tuple[str, str]:
    groups_r = f"length(unique(d[[{r_string(long.group)}]]))" if long.group else "NA"
    groups_py = f"d[{r_string(long.group)}].nunique()" if long.group else "np.nan"
    footer = R_POOLED_FOOTER if imputing else R_RANDOM + R_FOOTER
    r = footer.replace("PERSON_COLUMN", r_string(PERSON)).replace("GROUPS", groups_r)
    python = PYTHON_FOOTER.replace("PERSON_COLUMN", r_string(PERSON)).replace("GROUPS", groups_py)
    return r, python


def packages(imputing: Imputing | None) -> tuple[str, ...]:
    return (*PACKAGES, "mice", "mitml") if imputing else PACKAGES


def headers(result: CatalogResult, path: str, imputing: Imputing | None = None) -> tuple[str, str]:
    project = result.project.config.project.name
    return (
        R_HEADER.format(
            project=project,
            names=", ".join(packages(imputing)),
            install=install_command(packages(imputing)),
            path=r_string(path),
        ),
        PYTHON_HEADER.format(project=project, path=r_string(path)),
    )


def scripts(
    result: CatalogResult, model: Model, long: Long, label: str, imputing: Imputing | None = None
) -> tuple[str, str]:
    r_head, py_head = headers(result, DATA_FILE, imputing)
    r, python = code(model, long, label)
    if imputing:
        file = imputation.file_name(data_frame(long, True), imputation_plan(long, imputing))
        r = imputed_code(model, long, label, imputing, file)
        python = imputation.PYTHON_IMPUTE + python
    return f"{r_head}\n{r}", f"{py_head}\n{python}"


def run(
    result: CatalogResult,
    model: Model,
    long: Long,
    label: str,
    rscript: str | None,
    imputing: Imputing | None = None,
) -> Fitted:
    # R when the Settings page names an Rscript, otherwise the Python version, run here.
    r, python = code(model, long, label)
    r_footer, python_footer = footers(long, imputing is not None)
    frame = data_frame(long, imputing is not None)
    if imputing:
        file = imputation.cache_path(frame, imputation_plan(long, imputing)).as_posix()
        r = imputed_code(model, long, label, imputing, file)
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        frame.to_csv(folder / DATA_FILE, index=False)
        r_head, py_head = headers(result, (folder / DATA_FILE).as_posix(), imputing)
        if rscript:
            writes = [
                f"write.csv({name}, {r_string((folder / f'{name}.csv').as_posix())}, "
                "row.names = FALSE)"
                for name in OUTPUTS
            ]
            path = folder / "multilevel.R"
            check = package_check(packages(imputing))
            text = "\n".join([check, r_head, r, r_footer, *writes])
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
        reml_criterion=none(stats["reml_criterion"]),
        log_likelihood=none(stats["log_likelihood"]),
        aic=none(stats["aic"]),
        bic=none(stats["bic"]),
        singular=SINGULAR in notes,
        notes=[n for n in notes if n != SINGULAR],
        imputations=int(stats["imputations"]) if "imputations" in stats.index else None,
    )


def term_order(label: str, long: Long) -> int:
    # Formula order: intercept, time, then the covariates as chosen.
    labels = ["Intercept", long.time_label, *(c.label for c in long.covariates)]
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
        return long.time_label
    for c in long.covariates:
        if term == c.column:
            return c.label
        for _, level in c.levels:
            if term in (f"{c.column}{level}", f"{c.column}[T.{level}]"):
                return f"{c.label}: {level}"
    return term


def prediction(long: Long, fitted: Fitted) -> dict[float, float]:
    # Number covariates at their mean, answer covariates at the reference option.
    estimates = {t.label: t.estimate for t in fitted.fixed}
    used = long.frame.dropna()
    base = estimates["Intercept"] + sum(
        estimates[c.label] * used[c.column].mean() for c in long.covariates if not c.levels
    )
    slope = estimates.get(long.time_label, 0.0)
    # One point at each wave's mean time; with dates, people within a wave differ.
    times = sorted(used.groupby(WAVE)[TIME].mean())
    return {float(t): base + slope * t for t in times}


def references(long: Long) -> list[tuple[str, str]]:
    # The level each answer-option covariate is compared with: the first one with data.
    found = []
    used = long.frame.dropna()
    for c in long.covariates:
        present = [label for value, label in c.levels if (used[c.column] == value).any()]
        if present:
            found.append((c.label, present[0]))
    return found
