from dataclasses import dataclass

import pandas as pd

from labcatalog.pipeline import CatalogResult
from labcatalog.stats import multilevel as ml
from labcatalog.stats.analysis_script import Code, Variable, none, r_string
from labcatalog.stats.mplus import MISSING, WIDTH, data_text, statement, title_lines
from labcatalog.stats.summary import wave_order

MIN_WAVES = 3
RICLPM, EQUAL, CLPM = "riclpm", "riclpm_equal", "clpm"
MODELS = {
    RICLPM: "RI-CLPM",
    EQUAL: "RI-CLPM, lagged paths equal across waves",
    CLPM: "CLPM, no random intercepts",
}
# The comparisons, each the freer model against the more constrained.
TESTS = {"equal": (RICLPM, EQUAL), "intercepts": (RICLPM, CLPM)}
# lavaan's robust (MLR) fit measures and the names they go by here.
FIT = {
    "chisq.scaled": "chisq",
    "df.scaled": "df",
    "pvalue.scaled": "pvalue",
    "cfi.robust": "cfi",
    "tli.robust": "tli",
    "rmsea.robust": "rmsea",
    "srmr": "srmr",
    "aic": "aic",
    "bic": "bic",
}
# Each lagged path by the letters of the outcome and the predictor.
KINDS = {("x", "x"): "auto_x", ("y", "y"): "auto_y", ("y", "x"): "x_to_y", ("x", "y"): "y_to_x"}
LABELS = {"auto_x": "ax", "auto_y": "ay", "x_to_y": "cxy", "y_to_x": "cyx"}
DATA = "mplus_panel.dat"


@dataclass
class PanelModel:
    x_label: str
    y_label: str
    waves: list[str]
    # One variable per wave for each of X and Y.
    xs: list[Variable]
    ys: list[Variable]


@dataclass
class PanelPath:
    model: str
    lhs: str
    op: str
    rhs: str
    estimate: float
    se: float | None
    p: float | None
    low: float | None
    high: float | None
    standardized: float | None

    @property
    def kind(self) -> str | None:
        if self.op != "~":
            return None
        return KINDS[(self.lhs[1], self.rhs[1])]

    @property
    def wave(self) -> int:
        # The wave the path ends at, counting from 1.
        return int(self.lhs[2:])


@dataclass
class PanelFit:
    n: int
    fits: dict[str, dict[str, float | None]]
    paths: list[PanelPath]
    # Each comparison's scaled chi-square difference, its df and p.
    tests: dict[str, tuple[float, float, float]]

    def lagged(self, model: str, kind: str) -> list[PanelPath]:
        return sorted(
            (p for p in self.paths if p.model == model and p.kind == kind), key=lambda p: p.wave
        )

    def correlation(self, model: str, lhs: str, rhs: str) -> PanelPath | None:
        return next(
            (
                p
                for p in self.paths
                if p.model == model and p.op == "~~" and {p.lhs, p.rhs} == {lhs, rhs}
            ),
            None,
        )

    @property
    def equal_holds(self) -> bool:
        # Equal lagged paths fit no worse than free ones.
        return self.tests["equal"][2] >= 0.05


def choices(result: CatalogResult) -> dict[str, str]:
    # Scores and numbers measured at three or more waves of one study.
    return {
        key: label
        for key, label in ml.outcome_choices(result).items()
        if len(ml.wave_datasets(result, key)) >= MIN_WAVES
    }


def common_waves(result: CatalogResult, x: str, y: str) -> list[tuple[str, str, str]]:
    # Each wave both are measured at in one study, with the dataset of each.
    configs = {d.name: d for d in result.project.config.datasets}
    xs, ys = ml.wave_datasets(result, x), ml.wave_datasets(result, y)
    if not xs or not ys or configs[xs[0]].study != configs[ys[0]].study:
        return []
    by_wave = {configs[n].wave: n for n in ys}
    found = [
        (configs[n].wave, n, by_wave[configs[n].wave]) for n in xs if configs[n].wave in by_wave
    ]
    return sorted(found, key=lambda w: wave_order(w[0]))


def syntax(t: int, intercepts: bool, equal: bool) -> list[str]:
    # Random intercepts load 1 on every wave; within-person parts carry the lagged paths.
    xs, ys = [f"x{i}" for i in range(1, t + 1)], [f"y{i}" for i in range(1, t + 1)]
    lines = []
    if intercepts:
        lines += [f"RIx =~ {' + '.join(f'1*{v}' for v in xs)}"]
        lines += [f"RIy =~ {' + '.join(f'1*{v}' for v in ys)}"]
    lines += [f"w{v} =~ 1*{v}" for v in xs + ys]
    lines += [f"{v} ~~ 0*{v}" for v in xs + ys]
    for i in range(2, t + 1):
        label = {k: v if equal else f"{v}{i}" for k, v in LABELS.items()}
        lines.append(f"wx{i} ~ {label['auto_x']}*wx{i - 1} + {label['y_to_x']}*wy{i - 1}")
        lines.append(f"wy{i} ~ {label['auto_y']}*wy{i - 1} + {label['x_to_y']}*wx{i - 1}")
    lines += [f"wx{i} ~~ wy{i}" for i in range(1, t + 1)]
    lines += [f"w{v} ~~ w{v}" for v in xs + ys]
    if intercepts:
        lines += ["RIx ~~ RIx", "RIy ~~ RIy", "RIx ~~ RIy"]
        lines += [f"{ri} ~~ 0*{w}1" for ri in ("RIx", "RIy") for w in ("wx", "wy")]
    return lines


R_FIT = """\
fit_panel <- function(model) {{
  lavaan::lavaan(model, data = panel, estimator = "MLR", missing = "ml", meanstructure = TRUE,
                 int.ov.free = TRUE)
}}
fits <- list(riclpm = fit_panel(riclpm), riclpm_equal = fit_panel(riclpm_equal),
             clpm = fit_panel(clpm))
measures <- c({measures})
panel_fit <- do.call(rbind, lapply(names(fits), function(name) {{
  values <- as.list(unclass(lavaan::fitMeasures(fits[[name]], measures)))
  data.frame(c(list(model = name, n = lavaan::lavInspect(fits[[name]], "nobs")), values),
             check.names = FALSE)
}}))
print(panel_fit)
# The lagged paths, the random intercepts' variances and correlation, and the correlations
# within each wave, each with its fully standardized estimate.
panel_paths <- do.call(rbind, lapply(names(fits), function(name) {{
  e <- lavaan::parameterEstimates(fits[[name]])
  s <- lavaan::standardizedSolution(fits[[name]], se = FALSE)
  e$std <- s$est.std[match(paste(e$lhs, e$op, e$rhs), paste(s$lhs, s$op, s$rhs))]
  kept <- e$op == "~" | (e$op == "~~" & e$lhs != e$rhs & e$se > 0) |
    (e$op == "~~" & e$lhs == e$rhs & grepl("^RI", e$lhs))
  cbind(model = name, e[kept, c("lhs", "op", "rhs", "est", "se", "pvalue", "ci.lower",
                                "ci.upper", "std")])
}}))
print(panel_paths)
# Scaled chi-square difference tests (Satorra-Bentler): equal paths against free ones, and the
# model without random intercepts against the one with them, a test at the boundary.
compare <- function(free, fixed, label) {{
  test <- lavaan::lavTestLRT(fits[[free]], fits[[fixed]])
  data.frame(comparison = label, chisq = test[["Chisq diff"]][2], df = test[["Df diff"]][2],
             pvalue = test[["Pr(>Chisq)"]][2])
}}
panel_tests <- rbind(compare("riclpm", "riclpm_equal", "equal"),
                     compare("riclpm", "clpm", "intercepts"))
print(panel_tests)
"""


def panel_code(model: PanelModel) -> Code:
    t = len(model.waves)
    columns = [f"x{i} = d[[{r_string(v.column)}]]" for i, v in enumerate(model.xs, 1)]
    columns += [f"y{i} = d[[{r_string(v.column)}]]" for i, v in enumerate(model.ys, 1)]
    legend = ", ".join(
        f"{letter}{i} = {v.label} (wave {w})"
        for letter, variables in (("x", model.xs), ("y", model.ys))
        for i, (v, w) in enumerate(zip(variables, model.waves, strict=True), 1)
    )
    lines = [
        f"# Random intercept cross-lagged panel model of {model.x_label} (X) and {model.y_label} "
        f"(Y) over {t} waves,",
        "# in lavaan (MLR, missing values by full-information maximum likelihood): with the "
        "lagged paths free,",
        "# with them equal across waves, and the cross-lagged panel model without random "
        "intercepts (CLPM).",
        f"# {legend}",
        f"panel <- data.frame({', '.join(columns)})",
        "# Everyone with at least one value.",
        "panel <- panel[rowSums(!is.na(panel)) > 0, ]",
    ]
    for name, intercepts, equal in (
        ("riclpm", True, False),
        ("riclpm_equal", True, True),
        ("clpm", False, False),
    ):
        body = ",\n".join(f"  {r_string(s)}" for s in syntax(t, intercepts, equal))
        lines.append(f'{name} <- paste(\n{body},\n  sep = "\\n"\n)')
    measures = ", ".join(r_string(m) for m in FIT)
    return Code(
        title="Cross-lagged panel models",
        r="\n".join(lines) + "\n" + R_FIT.format(measures=measures),
        python="",
        outputs=("panel_fit", "panel_paths", "panel_tests"),
        packages=("lavaan",),
    )


def read_fit(found: dict[str, pd.DataFrame]) -> PanelFit:
    fits = {
        str(row["model"]): {name: none(row[key]) for key, name in FIT.items()}
        for _, row in found["panel_fit"].iterrows()
    }
    paths = [
        PanelPath(
            str(r["model"]),
            str(r["lhs"]),
            str(r["op"]),
            str(r["rhs"]),
            float(r["est"]),
            none(r["se"]),
            none(r["pvalue"]),
            none(r["ci.lower"]),
            none(r["ci.upper"]),
            none(r["std"]),
        )
        for _, r in found["panel_paths"].iterrows()
    ]
    tests = {
        str(r["comparison"]): (float(r["chisq"]), float(r["df"]), float(r["pvalue"]))
        for _, r in found["panel_tests"].iterrows()
    }
    return PanelFit(int(found["panel_fit"]["n"].iloc[0]), fits, paths, tests)


def mplus_syntax(t: int, intercepts: bool, equal: bool) -> list[str]:
    xs, ys = [f"x{i}" for i in range(1, t + 1)], [f"y{i}" for i in range(1, t + 1)]
    lines = []
    if intercepts:
        lines += [f"RIx BY {' '.join(f'{v}@1' for v in xs)};"]
        lines += [f"RIy BY {' '.join(f'{v}@1' for v in ys)};"]
    lines += [f"w{v} BY {v}@1;" for v in xs + ys]
    lines += [f"{' '.join(f'{v}@0' for v in xs + ys)};"]
    for i in range(2, t + 1):
        for outcome, predictor, kind in (
            ("wx", "wx", "auto_x"),
            ("wx", "wy", "y_to_x"),
            ("wy", "wy", "auto_y"),
            ("wy", "wx", "x_to_y"),
        ):
            label = f" ({LABELS[kind]})" if equal else ""
            lines.append(f"{outcome}{i} ON {predictor}{i - 1}{label};")
    lines += [f"wx{i} WITH wy{i};" for i in range(1, t + 1)]
    if intercepts:
        lines += ["RIx WITH RIy;", "RIx RIy WITH wx1@0 wy1@0;"]
    return lines


def mplus_files(model: PanelModel, frame: pd.DataFrame, title: str) -> dict[str, str]:
    t = len(model.waves)
    names = [f"x{i}" for i in range(1, t + 1)] + [f"y{i}" for i in range(1, t + 1)]
    columns = [v.column for v in model.xs + model.ys]
    data = frame[columns].set_axis(names, axis=1).dropna(how="all")
    files = {DATA: data_text(data)}
    for name, intercepts, equal in (
        ("riclpm", True, False),
        ("riclpm_equal", True, True),
        ("clpm", False, False),
    ):
        lines = [
            *title_lines(f"{title}, {MODELS[name]}"),
            *(f"! {n} = {c}"[:WIDTH] for n, c in zip(names, columns, strict=True)),
            "DATA:",
            f'  FILE = "{DATA}";',
            "VARIABLE:",
            *statement(f"NAMES = {' '.join(names)}"),
            f"  MISSING = ALL ({MISSING});",
            "ANALYSIS:",
            "  ESTIMATOR = MLR;",
            "MODEL:",
            *(f"  {line}" for line in mplus_syntax(t, intercepts, equal)),
            "OUTPUT:",
            "  STDYX;",
            "",
        ]
        files[f"mplus_{name}.inp"] = "\n".join(lines)
    return files
