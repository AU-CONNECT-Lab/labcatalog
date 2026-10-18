from dataclasses import dataclass, field

import pandas as pd

from labcatalog.pipeline import CatalogResult
from labcatalog.stats import multilevel as ml
from labcatalog.stats.analysis_script import Code, Variable, none, r_string
from labcatalog.stats.mplus import MISSING, WIDTH, data_text, statement, title_lines
from labcatalog.stats.summary import wave_order

MIN_WAVES = 3
RICLPM, EQUAL, CLPM = "riclpm", "riclpm_equal", "clpm"
STUDIES, EQUAL_STUDIES = "riclpm_studies", "riclpm_equal_studies"
MODELS = {
    RICLPM: "RI-CLPM",
    EQUAL: "RI-CLPM, lagged paths equal across waves",
    CLPM: "CLPM, no random intercepts",
}
# With several studies as groups, the same lagged paths held equal across them too.
STUDY_MODELS = {
    STUDIES: "RI-CLPM, lagged paths equal across studies",
    EQUAL_STUDIES: "RI-CLPM, lagged paths equal across waves and studies",
}
# Each model's random intercepts, lagged paths equal across waves, and across studies.
SHAPES = {
    RICLPM: (True, False, False),
    EQUAL: (True, True, False),
    CLPM: (False, False, False),
    STUDIES: (True, False, True),
    EQUAL_STUDIES: (True, True, True),
}
# The comparisons, each the freer model against the more constrained.
TESTS = {"equal": (RICLPM, EQUAL), "intercepts": (RICLPM, CLPM)}
STUDY_TESTS = {"studies": (RICLPM, STUDIES), "equal_studies": (EQUAL, EQUAL_STUDIES)}
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
STUDY = "study"


@dataclass
class PanelModel:
    x_label: str
    y_label: str
    waves: list[str]
    # One variable per wave for each of X and Y.
    xs: list[Variable]
    ys: list[Variable]
    # The studies' labels when several are groups, in the order of the data's study numbers.
    studies: list[str] = field(default_factory=list)

    @property
    def grouped(self) -> bool:
        return len(self.studies) > 1

    @property
    def models(self) -> dict[str, str]:
        return MODELS | STUDY_MODELS if self.grouped else MODELS


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
    group: int = 1

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

    def lagged(self, model: str, kind: str, group: int = 1) -> list[PanelPath]:
        return sorted(
            (p for p in self.paths if p.model == model and p.kind == kind and p.group == group),
            key=lambda p: p.wave,
        )

    def correlation(self, model: str, lhs: str, rhs: str, group: int = 1) -> PanelPath | None:
        return next(
            (
                p
                for p in self.paths
                if p.model == model
                and p.op == "~~"
                and p.group == group
                and {p.lhs, p.rhs} == {lhs, rhs}
            ),
            None,
        )

    @property
    def equal_holds(self) -> bool:
        # Equal lagged paths fit no worse than free ones.
        return self.tests["equal"][2] >= 0.05

    @property
    def studies_hold(self) -> bool | None:
        # Paths equal across studies fit no worse, for the model chosen over waves.
        test = self.tests.get("equal_studies" if self.equal_holds else "studies")
        return None if test is None else test[2] >= 0.05

    @property
    def chosen(self) -> str:
        # The model the paths are reported from.
        if self.studies_hold:
            return EQUAL_STUDIES if self.equal_holds else STUDIES
        return EQUAL if self.equal_holds else RICLPM


def choices(result: CatalogResult) -> dict[str, str]:
    # Scores and numbers measured at three or more waves of a study.
    studies = list(result.project.config.studies)
    return {
        key: label
        for key, label in ml.outcome_choices(result).items()
        if any(len(ml.wave_datasets(result, key, s)) >= MIN_WAVES for s in studies)
    }


def common_waves(
    result: CatalogResult, x: str, y: str, study: str | None = None
) -> list[tuple[str, str, str]]:
    # Each wave both are measured at in one study, with the dataset of each.
    configs = {d.name: d for d in result.project.config.datasets}
    xs, ys = ml.wave_datasets(result, x, study), ml.wave_datasets(result, y, study)
    if not xs or not ys or configs[xs[0]].study != configs[ys[0]].study:
        return []
    by_wave = {configs[n].wave: n for n in ys}
    found = [
        (configs[n].wave, n, by_wave[configs[n].wave]) for n in xs if configs[n].wave in by_wave
    ]
    return sorted(found, key=lambda w: wave_order(w[0]))


def panel_studies(result: CatalogResult, x: str, y: str) -> list[str]:
    # The studies where both are measured at three or more of the same waves.
    return [
        s for s in result.project.config.studies if len(common_waves(result, x, y, s)) >= MIN_WAVES
    ]


def labelled(name: str, groups: int, across: bool) -> str:
    # One label for every group holds a path equal across them; a label each frees it.
    if groups == 1 or across:
        return name
    return f"c({', '.join(f'{name}_g{g}' for g in range(1, groups + 1))})"


def syntax(
    t: int, intercepts: bool, equal: bool, groups: int = 1, across: bool = False
) -> list[str]:
    # Random intercepts load 1 on every wave; within-person parts carry the lagged paths.
    xs, ys = [f"x{i}" for i in range(1, t + 1)], [f"y{i}" for i in range(1, t + 1)]
    lines = []
    if intercepts:
        lines += [f"RIx =~ {' + '.join(f'1*{v}' for v in xs)}"]
        lines += [f"RIy =~ {' + '.join(f'1*{v}' for v in ys)}"]
    lines += [f"w{v} =~ 1*{v}" for v in xs + ys]
    lines += [f"{v} ~~ 0*{v}" for v in xs + ys]
    for i in range(2, t + 1):
        label = {k: labelled(v if equal else f"{v}{i}", groups, across) for k, v in LABELS.items()}
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
                 int.ov.free = TRUE{group})
}}
fits <- list({fits})
measures <- c({measures})
panel_fit <- do.call(rbind, lapply(names(fits), function(name) {{
  values <- as.list(unclass(lavaan::fitMeasures(fits[[name]], measures)))
  data.frame(c(list(model = name, n = sum(lavaan::lavInspect(fits[[name]], "nobs"))), values),
             check.names = FALSE)
}}))
print(panel_fit)
# The lagged paths, the random intercepts' variances and correlation, and the correlations
# within each wave, each with its fully standardized estimate{each}.
key <- function(x) paste(x$lhs, x$op, x$rhs, if (is.null(x$group)) 1 else x$group)
panel_paths <- do.call(rbind, lapply(names(fits), function(name) {{
  e <- lavaan::parameterEstimates(fits[[name]])
  s <- lavaan::standardizedSolution(fits[[name]], se = FALSE)
  e$std <- s$est.std[match(key(e), key(s))]
  e$group <- if (is.null(e$group)) 1 else e$group
  kept <- e$op == "~" | (e$op == "~~" & e$lhs != e$rhs & e$se > 0) |
    (e$op == "~~" & e$lhs == e$rhs & grepl("^RI", e$lhs))
  cbind(model = name, e[kept, c("lhs", "op", "rhs", "est", "se", "pvalue", "ci.lower",
                                "ci.upper", "std", "group")])
}}))
print(panel_paths)
# Scaled chi-square difference tests (Satorra-Bentler): equal paths against free ones, and the
# model without random intercepts against the one with them, a test at the boundary.
compare <- function(free, fixed, label) {{
  test <- lavaan::lavTestLRT(fits[[free]], fits[[fixed]])
  data.frame(comparison = label, chisq = test[["Chisq diff"]][2], df = test[["Df diff"]][2],
             pvalue = test[["Pr(>Chisq)"]][2])
}}
panel_tests <- rbind({tests})
print(panel_tests)
"""


def panel_code(model: PanelModel) -> Code:
    t = len(model.waves)
    groups = len(model.studies) if model.grouped else 1
    columns = [f"x{i} = d[[{r_string(v.column)}]]" for i, v in enumerate(model.xs, 1)]
    columns += [f"y{i} = d[[{r_string(v.column)}]]" for i, v in enumerate(model.ys, 1)]
    if model.grouped:
        columns.append(f"study = d[[{r_string(STUDY)}]]")
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
    ]
    if model.grouped:
        named = ", ".join(f"{n} = {s}" for n, s in enumerate(model.studies, start=1))
        lines += [
            "# The studies are groups, each with its own means and variances; two more models",
            "# hold the lagged paths equal across them, free or equal across waves.",
            f"# Study: {named}",
        ]
    lines += [
        f"panel <- data.frame({', '.join(columns)})",
        "# Everyone with at least one value.",
        'panel <- panel[rowSums(!is.na(panel[names(panel) != "study"])) > 0, ]',
    ]
    for name in model.models:
        intercepts, equal, across = SHAPES[name]
        body = ",\n".join(f"  {r_string(s)}" for s in syntax(t, intercepts, equal, groups, across))
        lines.append(f'{name} <- paste(\n{body},\n  sep = "\\n"\n)')
    tests = TESTS | (STUDY_TESTS if model.grouped else {})
    r = R_FIT.format(
        group=', group = "study"' if model.grouped else "",
        fits=", ".join(f"{n} = fit_panel({n})" for n in model.models),
        measures=", ".join(r_string(m) for m in FIT),
        each=", in each study" if model.grouped else "",
        tests=",\n                     ".join(
            f"compare({r_string(free)}, {r_string(fixed)}, {r_string(label)})"
            for label, (free, fixed) in tests.items()
        ),
    )
    return Code(
        title="Cross-lagged panel models",
        r="\n".join(lines) + "\n" + r,
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
            int(r["group"]),
        )
        for _, r in found["panel_paths"].iterrows()
    ]
    tests = {
        str(r["comparison"]): (float(r["chisq"]), float(r["df"]), float(r["pvalue"]))
        for _, r in found["panel_tests"].iterrows()
    }
    return PanelFit(int(found["panel_fit"]["n"].iloc[0]), fits, paths, tests)


def mplus_syntax(
    t: int, intercepts: bool, equal: bool, across: bool = False, group: int | None = None
) -> list[str]:
    # group numbers the labels of one study's block, freeing equal paths across studies; in
    # the overall model a label holds a path equal across the studies.
    xs, ys = [f"x{i}" for i in range(1, t + 1)], [f"y{i}" for i in range(1, t + 1)]
    lines = []
    if group is None:
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
            label = ""
            if equal:
                label = f" ({LABELS[kind]}{'' if group is None else f'_g{group}'})"
            elif across and group is None:
                label = f" ({LABELS[kind]}{i})"
            lines.append(f"{outcome}{i} ON {predictor}{i - 1}{label};")
    if group is None:
        lines += [f"wx{i} WITH wy{i};" for i in range(1, t + 1)]
        if intercepts:
            lines += ["RIx WITH RIy;", "RIx RIy WITH wx1@0 wy1@0;"]
    return lines


def group_lines(t: int, intercepts: bool, equal: bool, across: bool, group: int) -> list[str]:
    # One study's block: its own intercepts, and its own lagged paths unless held equal.
    names = [f"x{i}" for i in range(1, t + 1)] + [f"y{i}" for i in range(1, t + 1)]
    lines = [f"[{' '.join(names)}];"]
    if not across:
        lines += mplus_syntax(t, intercepts, equal, group=group)
    return lines


def mplus_files(model: PanelModel, frame: pd.DataFrame, title: str) -> dict[str, str]:
    t = len(model.waves)
    names = [f"x{i}" for i in range(1, t + 1)] + [f"y{i}" for i in range(1, t + 1)]
    columns = [v.column for v in model.xs + model.ys]
    data = frame[columns].set_axis(names, axis=1)
    if model.grouped:
        data[STUDY] = frame[STUDY].to_numpy()
    data = data.dropna(how="all", subset=names)
    files = {DATA: data_text(data)}
    grouping = []
    if model.grouped:
        named = " ".join(f"{n} = g{n}" for n in range(1, len(model.studies) + 1))
        grouping = [f"! g{n} = {s}"[:WIDTH] for n, s in enumerate(model.studies, start=1)]
    for name, label in model.models.items():
        intercepts, equal, across = SHAPES[name]
        factors = [f"w{v}" for v in names] + (["RIx", "RIy"] if intercepts else [])
        lines = [
            *title_lines(f"{title}, {label}"),
            *(f"! {n} = {c}"[:WIDTH] for n, c in zip(names, columns, strict=True)),
            *grouping,
            "DATA:",
            f'  FILE = "{DATA}";',
            "VARIABLE:",
            *statement(f"NAMES = {' '.join(names + ([STUDY] if model.grouped else []))}"),
            *statement(f"USEVARIABLES = {' '.join(names)}"),
            *(statement(f"GROUPING = {STUDY} ({named})") if model.grouped else []),
            f"  MISSING = ALL ({MISSING});",
            "ANALYSIS:",
            "  ESTIMATOR = MLR;",
            "MODEL:",
            *(f"  {line}" for line in mplus_syntax(t, intercepts, equal, across)),
        ]
        if model.grouped:
            # Each study's observed means are its own, so the factors' means stay at zero.
            lines += statement(f"[{' '.join(f'{f}@0' for f in factors)}]")
            for g in range(1, len(model.studies) + 1):
                lines.append(f"MODEL g{g}:")
                lines += [f"  {line}" for line in group_lines(t, intercepts, equal, across, g)]
        lines += ["OUTPUT:", "  STDYX;", ""]
        files[f"mplus_{name}.inp"] = "\n".join(lines)
    return files
