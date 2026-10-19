import re
import string
from dataclasses import dataclass, field

from labcatalog.config import ProjectConfig

BEFORE_PUNCTUATION = re.compile(r" (?=[,;)])")
METHODS = "Methods"
RESULTS = "Results"
# The file kinds that can hold their own wording of a template.
STUDY = "study"
INSTRUMENT = "instrument"


@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    default: str
    placeholders: tuple[str, ...]
    # Stand-in values for the preview of a template that needs an analysis run.
    example: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Template:
    key: str
    title: str
    part: str
    slots: tuple[Slot, ...]
    help: str = ""
    # The file that can hold its own wording, in place of the project's.
    own: str | None = None

    @property
    def single(self) -> bool:
        return len(self.slots) == 1

    def slot(self, key: str) -> Slot:
        return next(s for s in self.slots if s.key == key)


PARAGRAPH = "paragraph"
PAIR = ("a", "b", "direction", "statistic", "r", "p")
PAIR_EXAMPLE = {
    "a": "Sleep problems",
    "b": "Mood",
    "direction": "positively",
    "statistic": "r(118) = .32, p < .001",
    "r": "r(118) = .32",
    "p": "p < .001",
}
PAIR_NS_EXAMPLE = PAIR_EXAMPLE | {
    "direction": "negatively",
    "statistic": "r(118) = -.08, p = .384",
    "r": "r(118) = -.08",
    "p": "p = .384",
}
PAIRS_EXAMPLE = (
    "Sleep problems and Mood (r(118) = .32, p < .001) and Screen time and Mood (r(118) = -.21, "
    "p = .022)"
)
PREDICTOR = ("predictor", "outcome", "statistics", "b", "se", "p", "r2", "n")
PREDICTOR_EXAMPLE = {
    "predictor": "Sleep problems",
    "outcome": "Mood",
    "statistics": "b = 0.41, SE = 0.11, p < .001, R² = .10, n = 120",
    "b": "b = 0.41",
    "se": "SE = 0.11",
    "p": "p < .001",
    "r2": "R² = .10",
    "n": "n = 120",
}
PREDICTOR_NS_EXAMPLE = PREDICTOR_EXAMPLE | {
    "statistics": "b = 0.06, SE = 0.09, p = .512, R² = .00, n = 120",
    "b": "b = 0.06",
    "se": "SE = 0.09",
    "p": "p = .512",
    "r2": "R² = .00",
}
COMPARISON = ("outcome", "groups", "statistics", "test", "p", "effect")
TWO_EXAMPLE = {
    "outcome": "Mood",
    "groups": "Girls (M = 3.20, SD = 0.90) and Boys (M = 2.80, SD = 1.00)",
    "statistics": "Welch's t(117.6) = 2.30, p = .023, d = 0.42, 95% CI [0.06, 0.78]",
    "test": "Welch's t(117.6) = 2.30",
    "p": "p = .023",
    "effect": "d = 0.42, 95% CI [0.06, 0.78]",
}
TWO_NS_EXAMPLE = TWO_EXAMPLE | {
    "groups": "Girls (M = 3.00, SD = 0.90) and Boys (M = 2.90, SD = 1.00)",
    "statistics": "Welch's t(117.6) = 0.58, p = .563, d = 0.11, 95% CI [-0.25, 0.46]",
    "test": "Welch's t(117.6) = 0.58",
    "p": "p = .563",
    "effect": "d = 0.11, 95% CI [-0.25, 0.46]",
}
MORE_EXAMPLE = {
    "outcome": "Mood",
    "groups": "Wave 1 (M = 3.20, SD = 0.90), Wave 2 (M = 2.90, SD = 1.00), and Wave 3 (M = 2.60, "
    "SD = 0.80)",
    "statistics": "F(2, 177) = 6.40, p = .002, η² = .07, 95% CI [.01, .14]",
    "test": "F(2, 177) = 6.40",
    "p": "p = .002",
    "effect": "η² = .07, 95% CI [.01, .14]",
}
MORE_NS_EXAMPLE = MORE_EXAMPLE | {
    "statistics": "F(2, 177) = 1.10, p = .335, η² = .01, 95% CI [.00, .05]",
    "test": "F(2, 177) = 1.10",
    "p": "p = .335",
    "effect": "η² = .01, 95% CI [.00, .05]",
}
KAPPA_EXAMPLE = {
    "among": "between the two raters",
    "n": "60",
    "kappa": "κ = .71, 95% CI [.57, .85]",
}
MODEL_EXAMPLE = "a model with one factor for each subscale (Sadness and Worry)"
NAMES_EXAMPLE = "Sadness and Worry"
FITTED = ("Model", "model", "package", "estimation", "n", "fit", "indicators")
FITTED_EXAMPLE = {
    "Model": "A" + MODEL_EXAMPLE[1:],
    "model": MODEL_EXAMPLE,
    "package": "lavaan",
    "estimation": "the WLSMV estimator and the items as ordered categories",
    "n": "214",
    "fit": "χ²(19) = 31.20, p = .038, CFI = .98, TLI = .97, RMSEA = .05, 90% CI [.01, .09], "
    "SRMR = .04",
    "indicators": "items",
}
STEP_FIT_EXAMPLE = "χ²(38) = 52.40, CFI = .981, RMSEA = .042, SRMR = .051"
DESIGN = ("outcome", "package", "observations", "people")
DESIGN_EXAMPLE = {"outcome": "Mood", "package": "lme4", "observations": "512", "people": "180"}
LAGGED = ("predictor", "outcome", "b", "betas", "p")
LAGGED_EXAMPLE = {
    "predictor": "Sleep problems",
    "outcome": "Mood",
    "b": "b = 0.14",
    "betas": "(β from .12 to .15)",
    "p": "p = .006",
}
STEPS_EXAMPLE = {
    "predictor": "Sleep problems",
    "outcome": "Mood",
    "steps": "from wave 1 to 2, β = .18, p = .012 and from wave 2 to 3, β = .04, p = .561",
}
TEMPLATES: dict[str, Template] = {
    t.key: t
    for t in (
        Template(
            "participants",
            "Participants",
            METHODS,
            (
                Slot(
                    PARAGRAPH,
                    "Paragraph",
                    "{waves} {counts} {demographics} {retention} {modalities}",
                    (
                        "study",
                        "n_waves",
                        "waves",
                        "counts",
                        "demographics",
                        "retention",
                        "modalities",
                    ),
                ),
            ),
            "The Participants paragraph of the Methods page, for each study.",
            STUDY,
        ),
        Template(
            "measures",
            "Measures",
            METHODS,
            (
                Slot(
                    PARAGRAPH,
                    "Paragraph",
                    "We used {named}. {description} {items} {reverse} {scoring} {alpha} {omega}",
                    (
                        "name",
                        "abbreviation",
                        "cite",
                        "named",
                        "construct",
                        "reporter",
                        "n_items",
                        "scale",
                        "description",
                        "items",
                        "reverse",
                        "scoring",
                        "alpha",
                        "omega",
                    ),
                ),
            ),
            "Each instrument's paragraph, on the Methods page and the instrument's page.",
            INSTRUMENT,
        ),
        Template(
            "correlation",
            "Correlation",
            RESULTS,
            (
                Slot(
                    "pair",
                    "A significant correlation, when there are three or fewer",
                    "{a} was {direction} correlated with {b}, {statistic}.",
                    PAIR,
                    PAIR_EXAMPLE,
                ),
                Slot(
                    "pair_ns",
                    "A correlation that is not significant, when there are three or fewer",
                    "{a} was not significantly correlated with {b}, {statistic}.",
                    PAIR,
                    PAIR_NS_EXAMPLE,
                ),
                Slot(
                    "count",
                    "How many were significant, when there are more than three",
                    "Of the {n_pairs} correlations, {n_significant} {verb} significant at p < .05.",
                    ("n_pairs", "n_significant", "verb"),
                    {"n_pairs": "15", "n_significant": "6", "verb": "were"},
                ),
                Slot(
                    "within",
                    "When every significant one is between scores of the same instrument",
                    "All of them were between scores of the same instrument.",
                    (),
                ),
                Slot(
                    "strongest",
                    "The strongest between instruments, when more than five are",
                    "Between instruments, the {n_shown} strongest were between {pairs}.",
                    ("n_shown", "pairs"),
                    {"n_shown": "5", "pairs": PAIRS_EXAMPLE},
                ),
                Slot(
                    "between",
                    "Those between instruments, when two to five are",
                    "Between instruments, they were between {pairs}.",
                    ("pairs",),
                    {"pairs": PAIRS_EXAMPLE},
                ),
                Slot(
                    "between_one",
                    "The one between instruments",
                    "Between instruments, it was between {pairs}.",
                    ("pairs",),
                    {"pairs": "Sleep problems and Mood (r(118) = .32, p < .001)"},
                ),
                Slot(
                    "listed",
                    "Each pair in those lists",
                    "{a} and {b} ({statistic})",
                    PAIR,
                    PAIR_EXAMPLE,
                ),
            ),
            "The Results paragraph under the correlation table.",
        ),
        Template(
            "regression",
            "Regression",
            RESULTS,
            (
                Slot(
                    "intro",
                    "Before the predictors, when there is more than one",
                    "Each predictor was entered in its own simple regression.",
                    (),
                ),
                Slot(
                    "predictor",
                    "A significant predictor",
                    "{predictor} significantly predicted {outcome}, {statistics}.",
                    PREDICTOR,
                    PREDICTOR_EXAMPLE,
                ),
                Slot(
                    "predictor_ns",
                    "A predictor that is not significant",
                    "{predictor} did not significantly predict {outcome}, {statistics}.",
                    PREDICTOR,
                    PREDICTOR_NS_EXAMPLE,
                ),
            ),
            "The Results paragraph under the regression table.",
        ),
        Template(
            "missing",
            "Missing data",
            RESULTS,
            (
                Slot(
                    "all",
                    "When everyone has every value",
                    "All {people} people had values on the {variables}.",
                    ("people", "variables"),
                    {"people": "120", "variables": "4 variables"},
                ),
                Slot(
                    "complete",
                    "How many have every value",
                    "Of the {people} people, {complete} ({percent}) had values on {which}.",
                    ("people", "complete", "percent", "which"),
                    {
                        "people": "120",
                        "complete": "97",
                        "percent": "80.8%",
                        "which": "all 4 variables",
                    },
                ),
                Slot(
                    "each",
                    "When each variable lacks the same number",
                    "Each variable was missing for {missing} ({percent}).",
                    ("missing", "percent"),
                    {"missing": "6", "percent": "5.0%"},
                ),
                Slot(
                    "range",
                    "The fewest and most missing, when they differ",
                    "Missing values ranged from {low} ({low_percent}) for {low_label} to {high} "
                    "({high_percent}) for {high_label}.",
                    ("low", "low_percent", "low_label", "high", "high_percent", "high_label"),
                    {
                        "low": "2",
                        "low_percent": "1.7%",
                        "low_label": "Mood",
                        "high": "15",
                        "high_percent": "12.5%",
                        "high_label": "Sleep problems",
                    },
                ),
            ),
            "The Results paragraph of the Missing data tab.",
        ),
        Template(
            "groups",
            "Group comparison",
            RESULTS,
            (
                Slot(
                    "two",
                    "Two groups that differ significantly",
                    "{outcome} differed significantly between {groups}, {statistics}.",
                    COMPARISON,
                    TWO_EXAMPLE,
                ),
                Slot(
                    "two_ns",
                    "Two groups that do not differ significantly",
                    "{outcome} did not differ significantly between {groups}, {statistics}.",
                    COMPARISON,
                    TWO_NS_EXAMPLE,
                ),
                Slot(
                    "more",
                    "Three or more groups that differ significantly",
                    "{outcome} differed significantly among {groups}, {statistics}.",
                    COMPARISON,
                    MORE_EXAMPLE,
                ),
                Slot(
                    "more_ns",
                    "Three or more groups that do not differ significantly",
                    "{outcome} did not differ significantly among {groups}, {statistics}.",
                    COMPARISON,
                    MORE_NS_EXAMPLE,
                ),
                Slot(
                    "group",
                    "Each group in the list",
                    "{label} ({statistics})",
                    ("label", "statistics", "m", "sd"),
                    {
                        "label": "Girls",
                        "statistics": "M = 3.20, SD = 0.90",
                        "m": "M = 3.20",
                        "sd": "SD = 0.90",
                    },
                ),
            ),
            "The Results paragraph of the Group comparison tab.",
        ),
        Template(
            "agreement",
            "Rater agreement",
            RESULTS,
            (
                Slot(
                    "icc",
                    "Intraclass correlations, for ratings that are numbers",
                    "Agreement {among}, on the {n} people rated by {whom}, was {single} (two-way "
                    "random effects, absolute agreement, single rater); for the mean of the "
                    "raters, {mean}.",
                    ("among", "n", "whom", "single", "mean"),
                    {
                        "among": "between the two raters",
                        "n": "60",
                        "whom": "either",
                        "single": "ICC(2,1) = .81, 95% CI [.70, .88]",
                        "mean": "ICC(2,k) = .89, 95% CI [.82, .94]",
                    },
                ),
                Slot(
                    "kappa",
                    "Cohen's κ, for two raters",
                    "Agreement {among}, on the {n} people both rated, was Cohen's {kappa}.",
                    ("among", "n", "kappa"),
                    KAPPA_EXAMPLE,
                ),
                Slot(
                    "kappa_weighted",
                    "Cohen's κ with its weighted value, for ordered answers",
                    "Agreement {among}, on the {n} people both rated, was Cohen's {kappa}; with "
                    "quadratic weights, {weighted}.",
                    ("among", "n", "kappa", "weighted"),
                    KAPPA_EXAMPLE | {"weighted": "κ = .78, 95% CI [.66, .90]"},
                ),
                Slot(
                    "light",
                    "Light's κ, for three or more raters",
                    "Cohen's κ averaged over the {n_pairs} pairs of the {raters} raters (Light's "
                    "κ) was {light}, ranging from {low} to {high} across pairs.",
                    ("n_pairs", "raters", "light", "low", "high"),
                    {"n_pairs": "3", "raters": "3", "light": ".68", "low": ".61", "high": ".74"},
                ),
                Slot(
                    "studies",
                    "Each study on its own, with several studies",
                    "In each study on its own, {name} was {values}.",
                    ("name", "values"),
                    {"name": "ICC(2,1)", "values": ".79 in Study A and .84 in Study B"},
                ),
                Slot(
                    "study",
                    "Each study in that list",
                    "{value} in {study}",
                    ("value", "study"),
                    {"value": ".79", "study": "Study A"},
                ),
            ),
            "The Results paragraph of the Rater agreement tab.",
        ),
        Template(
            "cfa",
            "Measurement model",
            RESULTS,
            (
                Slot(
                    "fit",
                    "The model and its fit",
                    "{Model}, fitted in {package} with {estimation} (N = {n}), gave {fit}.",
                    FITTED,
                    FITTED_EXAMPLE,
                ),
                Slot(
                    "exact",
                    "A model with three indicators, which fits exactly",
                    "{Model}, fitted in {package} with {estimation} (N = {n}), fits exactly with "
                    "three {indicators}, so it has no fit indices.",
                    FITTED,
                    FITTED_EXAMPLE,
                ),
                Slot(
                    "problem",
                    "A model that could not be used",
                    "{Model} could not be used: {problem}.",
                    ("model", "Model", "problem"),
                    {
                        "model": MODEL_EXAMPLE,
                        "Model": "A" + MODEL_EXAMPLE[1:],
                        "problem": "a loading above 1",
                    },
                ),
                Slot(
                    "estimation_wlsmv",
                    "{estimation} with WLSMV",
                    "the WLSMV estimator and the {indicators} as ordered categories",
                    ("indicators",),
                    {"indicators": "items"},
                ),
                Slot(
                    "estimation_mlr",
                    "{estimation} with MLR",
                    "robust maximum likelihood (MLR) and the {indicators} as continuous",
                    ("indicators",),
                    {"indicators": "items"},
                ),
                Slot(
                    "estimation_ml",
                    "{estimation} with ML",
                    "maximum likelihood and the {indicators} as continuous",
                    ("indicators",),
                    {"indicators": "items"},
                ),
                Slot(
                    "model_one",
                    "{model} for one factor",
                    "a one-factor model of {names}",
                    ("names",),
                    {"names": "Total score"},
                ),
                Slot(
                    "model_subscales",
                    "{model} for a factor per subscale",
                    "a model with one factor for each subscale ({names})",
                    ("names",),
                    {"names": NAMES_EXAMPLE},
                ),
                Slot(
                    "model_second_order",
                    "{model} for a second-order model",
                    "a second-order model with a general factor over the subscales ({names})",
                    ("names",),
                    {"names": NAMES_EXAMPLE},
                ),
                Slot(
                    "model_subscale_scores",
                    "{model} for a factor of the subscale scores",
                    "a one-factor model of the subscale scores ({names})",
                    ("names",),
                    {"names": NAMES_EXAMPLE},
                ),
                Slot(
                    "model_measurement",
                    "{model} for a measurement model of several scores",
                    "a measurement model with a correlated factor for each of {names}",
                    ("names",),
                    {"names": "Mood, Sleep problems, and Stress"},
                ),
                Slot(
                    "covariates",
                    "When several studies are fitted together",
                    "Every factor was regressed on the study, so the factor correlations are "
                    "within studies.",
                    (),
                ),
                Slot(
                    "three_subscales",
                    "A second-order model over three subscales",
                    "With three subscales, its fit equals that of the subscale model.",
                    (),
                ),
                Slot(
                    "loadings",
                    "The standardized loadings",
                    "Standardized loadings ranged from {low} to {high}.",
                    ("low", "high"),
                    {"low": ".52", "high": ".84"},
                ),
                Slot(
                    "loadings_general",
                    "The loadings on a general factor",
                    "Standardized loadings of the subscales on the general factor ranged from "
                    "{low} to {high}.",
                    ("low", "high"),
                    {"low": ".61", "high": ".88"},
                ),
                Slot(
                    "hierarchical_omega",
                    "ω of a second-order model",
                    "Hierarchical ω was {omega}.",
                    ("omega",),
                    {"omega": ".79"},
                ),
                Slot(
                    "summed_omega",
                    "ω of the summed subscale scores",
                    "ω of the summed subscale scores was {omega}.",
                    ("omega",),
                    {"omega": ".83"},
                ),
                Slot(
                    "correlation",
                    "The correlation of two factors",
                    "The factors correlated {r}.",
                    ("r",),
                    {"r": ".46"},
                ),
                Slot(
                    "correlations",
                    "The correlations of three or more factors",
                    "Factor correlations ranged from {low} to {high}.",
                    ("low", "high"),
                    {"low": ".31", "high": ".58"},
                ),
                Slot(
                    "omega",
                    "ω of one factor",
                    "ω was {omega}.",
                    ("omega",),
                    {"omega": ".88"},
                ),
                Slot(
                    "omegas",
                    "ω of several factors",
                    "ω was {omegas}.",
                    ("omegas",),
                    {"omegas": ".81 for Sadness and .77 for Worry"},
                ),
                Slot(
                    "omega_each",
                    "Each factor in that list",
                    "{omega} for {score}",
                    ("omega", "score"),
                    {"omega": ".81", "score": "Sadness"},
                ),
            ),
            "The Results paragraph of a factor model, on the Measurement model tab and an "
            "instrument's page. The Invariance template uses its model descriptions.",
        ),
        Template(
            "invariance",
            "Invariance",
            RESULTS,
            (
                Slot(
                    "intro",
                    "The model and what it is tested across",
                    "Invariance of {model} across {across} was tested in steps, each holding one "
                    "more set of parameters equal.",
                    ("model", "across"),
                    {"model": MODEL_EXAMPLE, "across": "waves"},
                ),
                Slot(
                    "problem",
                    "A test that could not be run",
                    "Invariance of {model} across {across} could not be tested: {problem}.",
                    ("model", "across", "problem"),
                    {"model": MODEL_EXAMPLE, "across": "waves", "problem": "too few people"},
                ),
                Slot(
                    "freed",
                    "Parameters freed by labcatalog.yaml",
                    "Freed parameters: {freed}.",
                    ("freed",),
                    {"freed": "the intercept of item 3"},
                ),
                Slot(
                    "step",
                    "The first step",
                    "{step} gave {fit}.",
                    ("step", "fit"),
                    {"step": "The configural model", "fit": STEP_FIT_EXAMPLE},
                ),
                Slot(
                    "step_change",
                    "Each later step, against the one before",
                    "{step} gave {fit}; against the step before, {change}.",
                    ("step", "fit", "change"),
                    {
                        "step": "Adding equal loadings",
                        "fit": STEP_FIT_EXAMPLE,
                        "change": "Δχ²(6) = 7.10, p = .312, ΔCFI = -.002, ΔRMSEA = -.001",
                    },
                ),
                Slot(
                    "step_problem",
                    "A step that gave no usable model",
                    "{step} gave no usable model: {problem}.",
                    ("step", "problem"),
                    {"step": "Adding equal intercepts", "problem": "it did not converge"},
                ),
                Slot("configural", "{step} for the configural model", "The configural model", ()),
                Slot(
                    "thresholds", "{step} for equal thresholds", "Holding the thresholds equal", ()
                ),
                Slot("metric", "{step} for equal loadings", "Adding equal loadings", ()),
                Slot("scalar", "{step} for equal intercepts", "Adding equal intercepts", ()),
            ),
            "The Results paragraph of an invariance test, on an instrument's page and the "
            "Invariance tab.",
        ),
        Template(
            "multilevel",
            "Multilevel model",
            RESULTS,
            (
                Slot(
                    "design",
                    "The model and its data",
                    "A multilevel model of {outcome}, fitted by REML in {package}, used "
                    "{observations} observations from {people} people.",
                    DESIGN,
                    DESIGN_EXAMPLE,
                ),
                Slot(
                    "design_groups",
                    "The model and its data, with people in groups",
                    "A multilevel model of {outcome}, fitted by REML in {package}, used "
                    "{observations} observations from {people} people in {groups} groups.",
                    (*DESIGN, "groups"),
                    DESIGN_EXAMPLE | {"groups": "64"},
                ),
                Slot(
                    "icc",
                    "The ICC of each level",
                    "In the model with only the random intercepts, the ICC was {iccs}.",
                    ("iccs",),
                    {"iccs": ".42 at the person level and .18 at the family level"},
                ),
                Slot(
                    "icc_each",
                    "Each level in that list",
                    "{icc} at the {level} level",
                    ("icc", "level"),
                    {"icc": ".42", "level": "person"},
                ),
                Slot(
                    "fixed",
                    "The fixed effects",
                    "Fixed effects: {terms}.",
                    ("terms",),
                    {
                        "terms": "Wave, b = -0.12, SE = 0.04, t(118.2) = -3.00, p = .003, 95% CI "
                        "[-0.20, -0.04]"
                    },
                ),
                Slot(
                    "term",
                    "Each fixed effect, separated by semicolons",
                    "{term}, {statistics}",
                    ("term", "statistics", "b", "se", "test", "p", "ci"),
                    {
                        "term": "Wave",
                        "statistics": "b = -0.12, SE = 0.04, t(118.2) = -3.00, p = .003, 95% CI "
                        "[-0.20, -0.04]",
                        "b": "b = -0.12",
                        "se": "SE = 0.04",
                        "test": "t(118.2) = -3.00",
                        "p": "p = .003",
                        "ci": "95% CI [-0.20, -0.04]",
                    },
                ),
                Slot(
                    "random",
                    "The random effects",
                    "Random effects: {variances}.",
                    ("variances",),
                    {
                        "variances": "SD = 0.61 for the person intercepts and SD = 0.48 for the "
                        "residuals"
                    },
                ),
                Slot(
                    "intercepts",
                    "Random intercepts in that list",
                    "{sd} for the {level} intercepts",
                    ("sd", "level"),
                    {"sd": "SD = 0.61", "level": "person"},
                ),
                Slot(
                    "slopes",
                    "Random slopes in that list",
                    "{sd} for the {level} slopes of {term}",
                    ("sd", "level", "term"),
                    {"sd": "SD = 0.09", "level": "person", "term": "Wave"},
                ),
                Slot(
                    "slopes_r",
                    "Random slopes correlated with the intercepts",
                    "{sd} for the {level} slopes of {term} ({r} with the intercepts)",
                    ("sd", "level", "term", "r"),
                    {"sd": "SD = 0.09", "level": "person", "term": "Wave", "r": "r = -.31"},
                ),
                Slot(
                    "residual",
                    "The residuals in that list",
                    "{sd} for the residuals",
                    ("sd",),
                    {"sd": "SD = 0.48"},
                ),
                Slot(
                    "singular",
                    "A singular fit",
                    "The fit was singular, so some random effects are estimated as zero.",
                    (),
                ),
            ),
            "The Results paragraph of the Multilevel model tab.",
        ),
        Template(
            "panel",
            "Cross-lagged panel",
            RESULTS,
            (
                Slot(
                    "fit",
                    "The model and its fit",
                    "A random intercept cross-lagged panel model (RI-CLPM) of {x} and {y} over "
                    "{waves} waves (N = {n}) gave {fit}.",
                    ("x", "y", "waves", "n", "fit"),
                    {
                        "x": "Sleep problems",
                        "y": "Mood",
                        "waves": "3",
                        "n": "180",
                        "fit": "χ²(1) = 0.80, p = .371, CFI = 1.00, TLI = 1.00, RMSEA = .00, "
                        "SRMR = .01",
                    },
                ),
                Slot(
                    "equal",
                    "When equal lagged paths do not worsen fit",
                    "Holding the lagged paths equal across waves did not worsen fit, {change}, so "
                    "the lagged paths are reported from that model.",
                    ("change",),
                    {"change": "Δχ²(2) = 1.90, p = .387"},
                ),
                Slot(
                    "equal_worse",
                    "When equal lagged paths worsen fit",
                    "Holding the lagged paths equal across waves worsened fit, {change}, so the "
                    "lagged paths are reported as estimated at each wave.",
                    ("change",),
                    {"change": "Δχ²(2) = 9.40, p = .009"},
                ),
                Slot(
                    "intercepts",
                    "When the random intercepts improve fit",
                    "The random intercepts improved fit over the cross-lagged panel model without "
                    "them, {change}.",
                    ("change",),
                    {"change": "Δχ²(3) = 48.20, p < .001"},
                ),
                Slot(
                    "intercepts_ns",
                    "When the random intercepts do not improve fit",
                    "The random intercepts did not improve fit over the cross-lagged panel model "
                    "without them, {change}.",
                    ("change",),
                    {"change": "Δχ²(3) = 2.10, p = .552"},
                ),
                Slot(
                    "studies",
                    "With several studies, when equal paths across them do not worsen fit",
                    "With the {n_studies} studies as groups, holding the lagged paths equal "
                    "across them did not worsen fit, {change}, so they are reported from that "
                    "model, with β for each study.",
                    ("n_studies", "change"),
                    {"n_studies": "2", "change": "Δχ²(2) = 1.30, p = .522"},
                ),
                Slot(
                    "studies_worse",
                    "With several studies, when equal paths across them worsen fit",
                    "With the {n_studies} studies as groups, holding the lagged paths equal "
                    "across them worsened fit, {change}, so they are reported for each study.",
                    ("n_studies", "change"),
                    {"n_studies": "2", "change": "Δχ²(2) = 8.80, p = .012"},
                ),
                Slot(
                    "between",
                    "The correlation of the random intercepts",
                    "The random intercepts, the stable differences between people, correlated "
                    "{r}, {p}.",
                    ("r", "p"),
                    {"r": "r = .52", "p": "p < .001"},
                ),
                Slot(
                    "between_study",
                    "The same, for each of several studies",
                    "In {study}, the random intercepts, the stable differences between people, "
                    "correlated {r}, {p}.",
                    ("study", "r", "p"),
                    {"study": "Study A", "r": "r = .52", "p": "p < .001"},
                ),
                Slot(
                    "lagged",
                    "A lagged path held equal across waves",
                    "Within people, {predictor} predicted {outcome} at the next wave, {b} "
                    "{betas}, {p}.",
                    LAGGED,
                    LAGGED_EXAMPLE,
                ),
                Slot(
                    "lagged_study",
                    "The same, for each of several studies",
                    "In {study}, within people, {predictor} predicted {outcome} at the next wave, "
                    "{b} {betas}, {p}.",
                    ("study", *LAGGED),
                    LAGGED_EXAMPLE | {"study": "Study A"},
                ),
                Slot(
                    "lagged_steps",
                    "A lagged path estimated at each wave",
                    "Within people, {predictor} predicted {outcome} at the next wave {steps}.",
                    ("predictor", "outcome", "steps"),
                    STEPS_EXAMPLE,
                ),
                Slot(
                    "lagged_steps_study",
                    "The same, for each of several studies",
                    "In {study}, within people, {predictor} predicted {outcome} at the next wave "
                    "{steps}.",
                    ("study", "predictor", "outcome", "steps"),
                    STEPS_EXAMPLE | {"study": "Study A"},
                ),
                Slot(
                    "step",
                    "Each wave in that list",
                    "from wave {from_wave} to {to_wave}, {beta}, {p}",
                    ("from_wave", "to_wave", "beta", "p"),
                    {"from_wave": "1", "to_wave": "2", "beta": "β = .18", "p": "p = .012"},
                ),
            ),
            "The Results paragraph of the Cross-lagged panel tab.",
        ),
    )
}


@dataclass(frozen=True)
class Wording:
    # The project's templates; a part it does not set keeps the built-in wording.
    written: dict[str, str | dict[str, str]] = field(default_factory=dict)

    def text(self, key: str, slot: str = PARAGRAPH) -> str:
        found = self.written.get(key)
        own = found.get(slot) if isinstance(found, dict) else found
        return (own or TEMPLATES[key].slot(slot).default).strip()

    def say(self, key: str, slot: str, **values: object) -> str:
        text = " ".join(self.text(key, slot).format_map(values).split())
        # A placeholder that is empty, such as a β with no standardized value, leaves no gap.
        return BEFORE_PUNCTUATION.sub("", text)


def project_text(config: ProjectConfig, key: str, slot: str = PARAGRAPH) -> str:
    return Wording(config.templates).text(key, slot)


def placeholder_problem(template: str, allowed: tuple[str, ...]) -> str | None:
    try:
        fields = [f for _, f, _, _ in string.Formatter().parse(template) if f is not None]
    except ValueError as e:
        return f"{e}; write a literal brace as {{{{ or }}}}"
    wrong = [f for f in fields if f not in allowed]
    if wrong:
        return f"unknown placeholder {{{wrong[0]}}}; use one of {', '.join(allowed)}"
    return None


def shape_problem(key: str, written: object) -> str | None:
    found = TEMPLATES.get(key)
    if found is None:
        return f"unknown template {key}; use one of {', '.join(TEMPLATES)}"
    if found.single and not isinstance(written, str):
        return f"{key} is one text"
    if not found.single:
        if not isinstance(written, dict):
            return f"{key} names its parts: {', '.join(s.key for s in found.slots)}"
        wrong = [s for s in written if s not in {slot.key for slot in found.slots}]
        if wrong:
            return (
                f"{key} has no part {wrong[0]}; use one of {', '.join(s.key for s in found.slots)}"
            )
    return None
