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
    )
}


def project_text(config: ProjectConfig, key: str, slot: str = PARAGRAPH) -> str:
    written = config.templates.get(key)
    found = written.get(slot) if isinstance(written, dict) else written
    return (found or TEMPLATES[key].slot(slot).default).strip()


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
