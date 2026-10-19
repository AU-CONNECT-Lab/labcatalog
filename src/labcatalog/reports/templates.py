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
