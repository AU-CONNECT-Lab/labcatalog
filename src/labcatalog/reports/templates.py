import string
from dataclasses import dataclass, field

from labcatalog.config import ProjectConfig

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
        return " ".join(self.text(key, slot).format_map(values).split())


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
