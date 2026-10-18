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
PYTHON_ICC = """\
# Intraclass correlations are computed only in R (psych::ICC).
"""
R_KAPPA = """\
# Rater agreement: Cohen's kappa for each pair of raters, unweighted and with quadratic weights,
# with 95% CIs (psych::cohen.kappa), on everyone both of them rated.
raters <- c({columns})
pairs <- t(combn(raters, 2))
kappas <- do.call(rbind, lapply(seq_len(nrow(pairs)), function(i) {{
  both <- na.omit(d[pairs[i, ]])
  found <- psych::cohen.kappa(both)$confid
  data.frame(first = pairs[i, 1], second = pairs[i, 2], n = nrow(both),
             kappa = found[1, 2], kappa_low = found[1, 1], kappa_high = found[1, 3],
             weighted = found[2, 2], weighted_low = found[2, 1], weighted_high = found[2, 3])
}}))
print(kappas)
"""
PYTHON_KAPPA = """\
# Rater agreement: Cohen's kappa for each pair of raters, unweighted and with quadratic weights,
# with 95% CIs (statsmodels), on everyone both of them rated.
from statsmodels.stats.inter_rater import cohens_kappa

raters = [{columns}]
rows = []
for i, first in enumerate(raters):
    for second in raters[i + 1:]:
        both = d[[first, second]].dropna()
        levels = sorted(set(both[first]) | set(both[second]))
        table = pd.crosstab(both[first], both[second]).reindex(
            index=levels, columns=levels, fill_value=0).to_numpy()
        plain, weighted = cohens_kappa(table), cohens_kappa(table, wt="quadratic")
        rows.append(dict(first=first, second=second, n=len(both), kappa=plain.kappa,
                         kappa_low=plain.kappa_low, kappa_high=plain.kappa_upp,
                         weighted=weighted.kappa, weighted_low=weighted.kappa_low,
                         weighted_high=weighted.kappa_upp))
kappas = pd.DataFrame(rows)
print(kappas)
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

    @property
    def light(self) -> float | None:
        # Light's kappa: the mean of the pairs' unweighted kappas.
        values = [k.kappa for k in self.kappas or [] if k.kappa is not None]
        return sum(values) / len(values) if len(values) > 1 else None


def choices(result: CatalogResult, datasets: list[str], labels: dict[str, str]) -> dict[str, str]:
    # Every item with answer options of the chosen datasets, for categorical ratings.
    return {
        item_key(v): f"{item_label(result, v)} ({labels[v.dataset]})"
        for name in datasets
        for v in analysis.items_for(result, name)
        if v.type == CHOICE
    }


def kind_of(variables: list[Variable]) -> str:
    return KAPPA if all(v.kind == CHOICE for v in variables) else ICC


def agreement_code(variables: list[Variable]) -> Code:
    columns = ", ".join(r_string(v.column) for v in variables)
    if kind_of(variables) == KAPPA:
        return Code(
            title="Rater agreement",
            r=R_KAPPA.format(columns=columns),
            python=PYTHON_KAPPA.format(columns=columns),
            outputs=("kappas",),
            packages=("psych",),
        )
    return Code(
        title="Rater agreement",
        r=R_ICC.format(k=len(variables), columns=columns),
        python=PYTHON_ICC,
        outputs=("icc",),
        packages=("psych",),
    )


def read_agreement(found: dict[str, pd.DataFrame], variables: list[Variable]) -> Agreement:
    if "kappas" in found:
        pairs = [
            KappaPair(
                str(r.first),
                str(r.second),
                int(r.n),
                *(
                    none(getattr(r, k))
                    for k in (
                        "kappa",
                        "kappa_low",
                        "kappa_high",
                        "weighted",
                        "weighted_low",
                        "weighted_high",
                    )
                ),
            )
            for r in found["kappas"].itertuples()
        ]
        return Agreement(KAPPA, len(variables), kappas=pairs)
    frame = found["icc"]
    rows = [
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
    return Agreement(ICC, len(variables), n=int(frame["n"].iloc[0]), icc=rows)
