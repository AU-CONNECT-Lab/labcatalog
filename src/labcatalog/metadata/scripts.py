import shlex
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from labcatalog import defaults
from labcatalog.config import PrepareStep, ProjectConfig, SavedAnalysis, dataset_by_name
from labcatalog.exceptions import EditError
from labcatalog.metadata import editing, records
from labcatalog.metadata.browse import (
    Facet,
    RowIndex,
    as_set,
    dataset_facet_names,
    facet,
    wave_key,
    widened,
)
from labcatalog.metadata.changes import Change
from labcatalog.metadata.validate import same_file
from labcatalog.paths import posix_str
from labcatalog.project import Project


@dataclass(frozen=True)
class Language:
    name: str
    suffix: str
    command: str
    libraries: str
    arguments: str
    # A new script's first lines: read the input, write the output.
    skeleton: str


LANGUAGES = {
    "r": Language(
        "R",
        ".R",
        "Rscript",
        "base R",
        "commandArgs(trailingOnly = TRUE)",
        "args <- commandArgs(trailingOnly = TRUE)\n"
        "data <- read.csv(args[1])\n\n"
        "write.csv(data, args[2], row.names = FALSE)\n",
    ),
    "python": Language(
        "Python",
        ".py",
        "python",
        "the Python standard library and pandas",
        "sys.argv",
        "import sys\n\nimport pandas as pd\n\n"
        "data = pd.read_csv(sys.argv[1])\n\n"
        "data.to_csv(sys.argv[2], index=False)\n",
    ),
}
# The folders whose script files are listed, whether or not anything runs them.
SCRIPT_FOLDERS = (defaults.SCRIPTS_DIR, defaults.ANALYSES_DIR)


@dataclass
class Script:
    path: str
    steps: list[PrepareStep] = field(default_factory=list)
    analysis: SavedAnalysis | None = None


@dataclass
class Scripts:
    # Scripts the prepare steps run, in the order of their first step.
    steps: list[Script]
    # Steps whose command names no script file of the project.
    commands: list[PrepareStep]
    analyses: list[Script]
    # Script files in the scripts folders that nothing runs.
    unused: list[str]


def language_of(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return next((k for k, lang in LANGUAGES.items() if lang.suffix.lower() == suffix), None)


def command(language: str, script: str, source: str, target: str) -> str:
    quoted = [f'"{p}"' if " " in p else p for p in (script, source, target)]
    return " ".join([LANGUAGES[language].command, *quoted])


def script_of(root: Path, step: PrepareStep) -> str | None:
    # The first file of the command, or failing that of the inputs, that is a script.
    try:
        words = shlex.split(step.run)
    except ValueError:
        words = step.run.split()
    for word in [*words, *step.inputs]:
        if language_of(word) and (root / word).is_file():
            return PurePosixPath(word.replace("\\", "/")).as_posix()
    return None


def project_scripts(project: Project) -> Scripts:
    root = project.root
    by_path: dict[str, Script] = {}
    commands = []
    for step in project.config.prepare:
        found = script_of(root, step)
        if found is None:
            commands.append(step)
        else:
            by_path.setdefault(found, Script(found)).steps.append(step)
    analyses = [Script(a.script, analysis=a) for a in project.config.analyses]
    used = set(by_path) | {a.path for a in analyses}
    unused = [
        posix_str(path.relative_to(root))
        for folder in SCRIPT_FOLDERS
        for path in sorted((root / folder).glob("*"))
        if path.is_file()
        and language_of(path.name)
        and posix_str(path.relative_to(root)) not in used
    ]
    return Scripts(list(by_path.values()), commands, analyses, unused)


def new_script(root: Path, name: str, language: str) -> str:
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in name):
        raise EditError("A script name uses lower-case letters, digits and _ only")
    relative = f"{defaults.SCRIPTS_DIR}/{name}{LANGUAGES[language].suffix}"
    path = root / relative
    if path.exists():
        raise EditError(f"{relative} already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(LANGUAGES[language].skeleton, encoding="utf-8")
    return relative


def step_change(project: Project, old: str | None, step: PrepareStep) -> Change:
    # The step takes the place of the one named old, or runs last when old is None.
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    steps = data.setdefault("prepare", CommentedSeq())
    taken = {str(s.get("name")) for s in steps} - {old}
    if step.name in taken:
        raise EditError(f"Another step is already named {step.name}")
    entry = CommentedMap(step.model_dump(exclude_none=True))
    entry.fa.set_flow_style()
    for key in ("inputs", "outputs"):
        entry[key] = CommentedSeq(entry[key])
        entry[key].fa.set_flow_style()
    at = next((n for n, s in enumerate(steps) if s.get("name") == old), None)
    if at is None:
        steps.append(entry)
    else:
        steps[at] = entry
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


def remove_step_change(project: Project, name: str) -> Change:
    opened = editing.open_file(project.root, defaults.CONFIG_FILENAME)
    data = records.load(opened.text)
    steps = data.get("prepare") or CommentedSeq()
    del steps[next(n for n, s in enumerate(steps) if s.get("name") == name)]
    if not steps:
        data.pop("prepare", None)
    return Change(defaults.CONFIG_FILENAME, records.dumped(data), opened)


STAGE, STATUS, LANGUAGE = "stage", "status", "language"
PREPARE, ANALYSIS, UNUSED = "prepare", "analysis", "unused"
NO_STAGE = "none"
# The stages of the work, in the order data goes through them, with the scripts nothing runs.
STAGES = {
    "clean": "Clean",
    "process": "Process",
    "extract": "Extract",
    "score": "Score",
    NO_STAGE: "No stage",
    ANALYSIS: "Analyses",
    UNUSED: "Not run",
}
# What each stage of a prepare step does, for the step's dialog and the New script window.
STAGE_HELP = {
    "clean": "turns a raw export into a dataset's file",
    "process": "runs a modality's pipeline on raw recordings",
    "extract": "gathers each person's pipeline output into one row per person",
    "score": "computes an instrument's scores",
}
STATUSES = ("up to date", "outdated", "missing output", "missing input")


@dataclass
class Entry:
    # One line of the Scripts page: a script, or a step whose command names no script.
    key: str
    kind: str
    script: Script | None = None
    step: PrepareStep | None = None
    datasets: list[str] = field(default_factory=list)

    @property
    def steps(self) -> list[PrepareStep]:
        return self.script.steps if self.script else [self.step]


def entries(project: Project, found: Scripts) -> list[Entry]:
    return [
        *(Entry(s.path, PREPARE, s, datasets=written(project, s.steps)) for s in found.steps),
        *(
            Entry(f"step:{s.name}", PREPARE, step=s, datasets=written(project, [s]))
            for s in found.commands
        ),
        *(Entry(s.path, ANALYSIS, s, datasets=list(s.analysis.datasets)) for s in found.analyses),
        *(Entry(p, UNUSED, Script(p)) for p in found.unused),
    ]


def written(project: Project, steps: list[PrepareStep]) -> list[str]:
    # The datasets whose files the steps write.
    outputs = {same_file(project, path) for step in steps for path in step.outputs}
    return [
        d.name for d in project.config.datasets if d.path and same_file(project, d.path) in outputs
    ]


def script_index(project: Project, listed: list[Entry], statuses: dict[str, str]) -> RowIndex:
    # statuses: each prepare step's status, by name.
    config = project.config
    names = dataset_facet_names(config)
    values, text = {}, {}
    for entry in listed:
        datasets = [dataset_by_name(config, d) for d in entry.datasets if has_dataset(config, d)]
        found = {name: set() for name in names}
        for d in datasets:
            known = {
                "study": d.study,
                "wave": wave_key(d.study, d.wave),
                "reporter": d.reporter,
                "modality": d.modality,
            }
            custom = {**config.studies[d.study].custom, **d.custom}
            for name in names:
                found[name] |= as_set(known[name] if name in known else custom.get(name))
        path = entry.script.path if entry.script else ""
        language = language_of(path)
        found[STAGE] = stages_of(entry)
        found[STATUS] = {statuses[s.name] for s in entry.steps if entry.kind == PREPARE}
        found[LANGUAGE] = {language} if language else set()
        values[entry.key] = widened(config, found)
        parts = [path, *entry.datasets]
        for step in entry.steps if entry.kind == PREPARE else []:
            parts += [step.name, step.run, *step.inputs, *step.outputs]
        if entry.script and entry.script.analysis:
            parts += [entry.script.analysis.name, entry.script.analysis.request]
        text[entry.key] = "\n".join(parts).lower()
    # A script of the project's own, writing no dataset, shows whatever datasets are chosen.
    rows = list(values.values())
    every = {name: {v for row in rows for v in row[name]} for name in names}
    for row in rows:
        if not any(row[name] for name in names):
            for name in names:
                row[name] = set(every[name])
    present = {name: {v for row in rows for v in row[name]} for name in (STAGE, STATUS, LANGUAGE)}
    return RowIndex(
        keys=[e.key for e in listed],
        facets=[
            Facet(STAGE, "Stage", {k: v for k, v in STAGES.items() if k in present[STAGE]}),
            *(facet(config, name, rows) for name in names),
            Facet(STATUS, "Status", {s: s for s in STATUSES if s in present[STATUS]}),
            Facet(
                LANGUAGE,
                "Language",
                {k: v.name for k, v in LANGUAGES.items() if k in present[LANGUAGE]},
            ),
        ],
        values=values,
        text=text,
    )


def stages_of(entry: Entry) -> set[str]:
    if entry.kind != PREPARE:
        return {entry.kind}
    return {s.stage or NO_STAGE for s in entry.steps}


def has_dataset(config: ProjectConfig, name: str) -> bool:
    return any(d.name == name for d in config.datasets)
