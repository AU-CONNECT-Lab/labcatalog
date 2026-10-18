from dataclasses import dataclass

import pandas as pd

from labcatalog.pipeline import CatalogResult
from labcatalog.stats import analysis
from labcatalog.stats.analysis_script import (
    CHOICE,
    Code,
    Variable,
    item_key,
    item_label,
    none,
    r_string,
)

ICC = "icc"
KAPPA = "kappa"
# psych::ICC's rows and the names they go by.
ICC_TYPES = {
    "ICC1": "ICC(1,1): one-way random, single rater",
    "ICC2": "ICC(2,1): two-way random, absolute agreement, single rater",
    "ICC3": "ICC(3,1): two-way mixed, consistency, single rater",
    "ICC1k": "ICC(1,k): one-way random, mean of the raters",
    "ICC2k": "ICC(2,k): two-way random, absolute agreement, mean of the raters",
    "ICC3k": "ICC(3,k): two-way mixed, consistency, mean of the raters",
}

R_ICC = """\
# Rater agreement: the intraclass correlations of the {k} raters with their 95% CIs
# (psych::ICC), on everyone all of them rated.
raters <- c({columns})
ratings <- na.omit(d[raters])
found <- psych::ICC(ratings, lmer = FALSE)$results
icc <- data.frame(type = found$type, icc = found$ICC, low = found[["lower bound"]],
                  high = found[["upper bound"]], f = found$F, df1 = found$df1, df2 = found$df2,
                  p = found$p, n = nrow(ratings))
print(icc)
"""
R_STUDY_ICC = """\
# Rater agreement pooled over studies: the intraclass correlations of the {k} raters with their
# 95% CIs (psych::ICC), on everyone all of them rated, within studies: each rating less its
# study's mean rating, so a difference between the studies does not count as agreement. Then
# each study on its own.
raters <- c({columns})
keep <- complete.cases(d[raters])
ratings <- d[keep, raters]
study <- d$study[keep]
centred <- ratings - ave(rowMeans(ratings), study)
found <- psych::ICC(centred, lmer = FALSE)$results
icc <- data.frame(type = found$type, icc = found$ICC, low = found[["lower bound"]],
                  high = found[["upper bound"]], f = found$F, df1 = found$df1, df2 = found$df2,
                  p = found$p, n = nrow(ratings))
print(icc)
study_icc <- do.call(rbind, lapply(sort(unique(study)), function(k) {{
  part <- psych::ICC(ratings[study == k, ], lmer = FALSE)$results
  data.frame(study = k, type = part$type, icc = part$ICC, low = part[["lower bound"]],
             high = part[["upper bound"]], f = part$F, df1 = part$df1, df2 = part$df2,
             p = part$p, n = sum(study == k))
}}))
print(study_icc)
"""
PYTHON_ICC = """\
# Intraclass correlations are computed only in R (psych::ICC).
"""
R_KAPPA = """\
# Rater agreement: Cohen's kappa for each pair of raters, unweighted and with quadratic weights,
# with 95% CIs (psych::cohen.kappa), on everyone both of them rated.
raters <- c({columns})
pairs <- t(combn(raters, 2))
kappa_pairs <- function(data) {{
  do.call(rbind, lapply(seq_len(nrow(pairs)), function(i) {{
    both <- na.omit(data[pairs[i, ]])
    found <- psych::cohen.kappa(both)$confid
    data.frame(first = pairs[i, 1], second = pairs[i, 2], n = nrow(both),
               kappa = found[1, 2], kappa_low = found[1, 1], kappa_high = found[1, 3],
               weighted = found[2, 2], weighted_low = found[2, 1], weighted_high = found[2, 3])
  }}))
}}
kappas <- kappa_pairs(d)
print(kappas)
"""
R_STUDY_KAPPA = """# The same pairs in each study on its own.
study_kappas <- do.call(rbind, lapply(sort(unique(d$study)), function(k) {{
  cbind(study = k, kappa_pairs(d[d$study == k, ]))
}}))
print(study_kappas)
"""
PYTHON_KAPPA = """\
# Rater agreement: Cohen's kappa for each pair of raters, unweighted and with quadratic weights,
# with 95% CIs (statsmodels), on everyone both of them rated.
from statsmodels.stats.inter_rater import cohens_kappa

raters = [{columns}]


def kappa_pairs(data):
    rows = []
    for i, first in enumerate(raters):
        for second in raters[i + 1:]:
            both = data[[first, second]].dropna()
            levels = sorted(set(both[first]) | set(both[second]))
            table = pd.crosstab(both[first], both[second]).reindex(
                index=levels, columns=levels, fill_value=0).to_numpy()
            plain, weighted = cohens_kappa(table), cohens_kappa(table, wt="quadratic")
            rows.append(dict(first=first, second=second, n=len(both), kappa=plain.kappa,
                             kappa_low=plain.kappa_low, kappa_high=plain.kappa_upp,
                             weighted=weighted.kappa, weighted_low=weighted.kappa_low,
                             weighted_high=weighted.kappa_upp))
    return pd.DataFrame(rows)


kappas = kappa_pairs(d)
print(kappas)
"""
PYTHON_STUDY_KAPPA = """# The same pairs in each study on its own.
study_kappas = pd.concat([kappa_pairs(part).assign(study=k) for k, part in d.groupby("study")])
print(study_kappas)
"""


@dataclass
class IccRow:
    type: str
    icc: float
    low: float | None
    high: float | None
    f: float
    df1: float
    df2: float
    p: float


@dataclass
class KappaPair:
    first: str
    second: str
    n: int
    kappa: float | None
    kappa_low: float | None
    kappa_high: float | None
    weighted: float | None
    weighted_low: float | None
    weighted_high: float | None


@dataclass
class Agreement:
    kind: str
    raters: int
    # Everyone all raters rated, for the ICC.
    n: int = 0
    icc: list[IccRow] | None = None
    kappas: list[KappaPair] | None = None
    # Each study's own, by study number, when the sample pools studies.
    study_icc: dict[float, list[IccRow]] | None = None
    study_kappas: dict[float, list[KappaPair]] | None = None
    study_n: dict[float, int] | None = None

    @property
    def light(self) -> float | None:
        # Light's kappa: the mean of the pairs' unweighted kappas.
        values = [k.kappa for k in self.kappas or [] if k.kappa is not None]
        return sum(values) / len(values) if len(values) > 1 else None


def choices(result: CatalogResult, datasets: list[str], labels: dict[str, str]) -> dict[str, str]:
    # Every item with answer options of the chosen datasets, for categorical ratings.
    found = {
        item_key(v): f"{item_label(result, v)} ({labels[v.dataset]})"
        for name in datasets
        for v in analysis.items_for(result, name)
        if v.type == CHOICE
    }
    if analysis.pooling(result, datasets):
        return analysis.pooled(result, datasets, found)
    return found


def kind_of(variables: list[Variable]) -> str:
    return KAPPA if all(v.kind == CHOICE for v in variables) else ICC


def agreement_code(variables: list[Variable], by_study: bool = False) -> Code:
    columns = ", ".join(r_string(v.column) for v in variables)
    if kind_of(variables) == KAPPA:
        r, python = R_KAPPA, PYTHON_KAPPA
        if by_study:
            r, python = r + R_STUDY_KAPPA, python + PYTHON_STUDY_KAPPA
        return Code(
            title="Rater agreement",
            r=r.format(columns=columns),
            python=python.format(columns=columns),
            outputs=("kappas", *(("study_kappas",) if by_study else ())),
            packages=("psych",),
        )
    return Code(
        title="Rater agreement",
        r=(R_STUDY_ICC if by_study else R_ICC).format(k=len(variables), columns=columns),
        python=PYTHON_ICC,
        outputs=("icc", *(("study_icc",) if by_study else ())),
        packages=("psych",),
    )


KAPPA_FIELDS = ("kappa", "kappa_low", "kappa_high", "weighted", "weighted_low", "weighted_high")


def kappa_pairs(frame: pd.DataFrame) -> list[KappaPair]:
    return [
        KappaPair(
            str(r.first), str(r.second), int(r.n), *(none(getattr(r, k)) for k in KAPPA_FIELDS)
        )
        for r in frame.itertuples()
    ]


def read_agreement(found: dict[str, pd.DataFrame], variables: list[Variable]) -> Agreement:
    if "kappas" in found:
        agreement = Agreement(KAPPA, len(variables), kappas=kappa_pairs(found["kappas"]))
        if "study_kappas" in found:
            each = found["study_kappas"]
            agreement.study_kappas = {
                float(k): kappa_pairs(part) for k, part in each.groupby("study", sort=True)
            }
        return agreement
    frame = found["icc"]
    agreement = Agreement(ICC, len(variables), n=int(frame["n"].iloc[0]), icc=icc_rows(frame))
    if "study_icc" in found:
        parts = dict(list(found["study_icc"].groupby("study", sort=True)))
        agreement.study_icc = {float(k): icc_rows(part) for k, part in parts.items()}
        agreement.study_n = {float(k): int(part["n"].iloc[0]) for k, part in parts.items()}
    return agreement


def icc_rows(frame: pd.DataFrame) -> list[IccRow]:
    return [
        IccRow(
            str(r.type),
            float(r.icc),
            none(r.low),
            none(r.high),
            float(r.f),
            float(r.df1),
            float(r.df2),
            float(r.p),
        )
        for r in frame.itertuples()
    ]
