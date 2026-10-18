from dataclasses import dataclass, field
from itertools import product

import pandas as pd

from labcatalog.stats.analysis_script import Variable, none
from labcatalog.stats.cfa import ML, MLR, WLSMV

PATHS = ("a", "b", "c")
MAX_MODERATORS = 2
SCORE_ESTIMATORS = (ML, MLR)
ITEM_ESTIMATORS = (WLSMV, ML, MLR)
# modsem's latent interactions treat the items as continuous.
MODERATED_ITEM_ESTIMATORS = (ML, MLR)
DEFAULT_BOOTSTRAP = 1000
DEFAULT_WORKERS = 4
SEED = 1
ESTIMATOR_NAMES = {
    ML: "maximum likelihood",
    MLR: "robust maximum likelihood (MLR)",
    WLSMV: "WLSMV with the items as ordered categories",
}
# Bootstrap refits with the plain estimator, whose estimates the robust one shares.
BASE = {ML: "ML", MLR: "ML", WLSMV: "DWLS"}
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
    WLSMV: (
        "chisq.scaled",
        "df.scaled",
        "pvalue.scaled",
        "cfi.scaled",
        "tli.scaled",
        "rmsea.scaled",
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
    "cfi.scaled": "cfi",
    "tli.scaled": "tli",
    "rmsea.scaled": "rmsea",
}
LAVAAN = "lavaan"
MODSEM = "modsem"


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
    # Up to two, each on its own paths; with two, their interactions add, with no three-way term.
    moderators: list[Moderator] = field(default_factory=list)
    estimator: str = ML
    bootstrap: int = DEFAULT_BOOTSTRAP
    # X, M, Y and a moderator with items become factors of their items.
    items: bool = False

    @property
    def moderated(self) -> set[str]:
        return {p for m in self.moderators for p in m.paths}

    @property
    def tags(self) -> list[str]:
        # One moderator keeps the plain names (w, a_xw); two are told apart as w1, a_xw1 and w2.
        if len(self.moderators) == 1:
            return [""]
        return [str(k) for k in range(1, len(self.moderators) + 1)]

    def on(self, path: str) -> list[int]:
        return [k for k, m in enumerate(self.moderators) if path in m.paths]

    def latent(self, k: int) -> bool:
        return self.items and bool(self.moderators[k].variable.items)

    @property
    def package(self) -> str:
        return MODSEM if self.items and self.moderators else LAVAAN

    @property
    def latent_moderator(self) -> bool:
        return bool(self.moderators) and all(self.latent(k) for k in range(len(self.moderators)))

    @property
    def method(self) -> str:
        # LMS needs the moderator to be a factor; QML also takes an observed one.
        return "lms" if self.latent_moderator else "qml"


@dataclass
class Effect:
    label: str
    estimate: float
    se: float | None
    p: float | None
    low: float | None
    high: float | None
    standardized: float | None = None


@dataclass
class MediationFit:
    n: int
    # Keyed by label: a, b, c, a_w, a_xw, y_w, b_mw, c_xw, indirect, total, index, and the
    # conditional effects that conditions() names; with two moderators the labels end in 1 or 2.
    effects: dict[str, Effect]
    fit: dict[str, float | None]
    # Each moderator's values, in its own units, at which the conditional effects are taken.
    at: list[list[float]] = field(default_factory=list)
    estimator: str = ML
    bootstrap: int = DEFAULT_BOOTSTRAP
    resamples: int = DEFAULT_BOOTSTRAP
    package: str = LAVAAN
    method: str = ""


def read_fit(found: dict[str, pd.DataFrame], model: MediationModel) -> MediationFit:
    effects = {
        row["label"]: Effect(
            row["label"],
            float(row["est"]),
            none(row["se"]),
            none(row["pvalue"]),
            none(row["ci.lower"]),
            none(row["ci.upper"]),
            # Effects at numbers on the moderator's own scale have no standardized form.
            None if conditional(row["label"]) else none(row["std"]),
        )
        for _, row in found["effects"].iterrows()
    }
    measures = found["model_fit"].iloc[0]
    fit = (
        {FIT_NAMES.get(k, k): none(measures[k]) for k in FIT[model.estimator]}
        if model.package == LAVAAN
        else {}
    )
    values = found["moderator_values"]
    return MediationFit(
        n=int(measures["n"]),
        effects=effects,
        fit=fit,
        at=[
            [float(v) for v in values["value"][values["moderator"] == k]]
            for k in range(1, len(model.moderators) + 1)
        ],
        estimator=model.estimator,
        bootstrap=model.bootstrap,
        resamples=int(measures["resamples"]),
        package=model.package,
        method=model.method if model.package == MODSEM else "",
    )


def conditional(label: str) -> bool:
    return label == "index" or label.startswith(("index_", "indirect_", "direct_"))


def depends(model: MediationModel, kind: str) -> list[int]:
    # The moderators a conditional effect varies with: on a or b for the indirect, on c the direct.
    paths = {"a", "b"} if kind == "indirect" else {"c"}
    return [k for k, m in enumerate(model.moderators) if paths & set(m.paths)]


def conditional_label(model: MediationModel, kind: str, spots: list[tuple[int, int]]) -> str:
    # spots holds (moderator, its value's place from 1) for each moderator the effect varies with.
    if len(model.moderators) == 1:
        return f"{kind}_{spots[0][1]}"
    return f"{kind}_" + "_".join(f"w{k + 1}_{i}" for k, i in spots)


def conditions(
    model: MediationModel, fit: MediationFit, kind: str
) -> list[tuple[str, list[tuple[int, int]]]]:
    # Every combination of the values of the moderators the effect varies with.
    which = depends(model, kind)
    if not which:
        return []
    grid = product(*(range(1, len(fit.at[k]) + 1) for k in which))
    found = []
    for places in grid:
        spots = list(zip(which, places, strict=True))
        found.append((conditional_label(model, kind, spots), spots))
    return found


def indexed(model: MediationModel) -> list[int]:
    # A moderator has an index of (partial) moderated mediation when the indirect effect is
    # linear in it: it moderates one of a and b, and nothing moderates the other.
    on_a, on_b = model.on("a"), model.on("b")
    return [k for k in on_a if not on_b] + [k for k in on_b if not on_a]


def index_label(model: MediationModel, k: int) -> str:
    return "index" if len(model.moderators) == 1 else f"index_{k + 1}"


def at_labels(variable: Variable, values: list[float]) -> list[str]:
    # Where the conditional effects are taken, in words.
    if len(values) == 2:
        options = dict(variable.options)
        return [options.get(v, f"{v:g}") for v in values]
    return ["1 SD below the mean", "the mean", "1 SD above the mean"]


def intervals_text(fit: MediationFit) -> str:
    if not fit.bootstrap:
        return "Wald intervals, by the delta method for the defined effects"
    done = (
        fit.bootstrap if fit.resamples >= fit.bootstrap else f"{fit.resamples} of {fit.bootstrap}"
    )
    return f"percentile bootstrap intervals from {done} resamples"


def method_text(fit: MediationFit) -> str:
    name = ESTIMATOR_NAMES[fit.estimator]
    if fit.package == MODSEM:
        return f"latent interactions by {fit.method.upper()} with {name}"
    if fit.bootstrap and fit.estimator != ML:
        return f"{BASE[fit.estimator]} for the estimates and {name} for the fit"
    return name
