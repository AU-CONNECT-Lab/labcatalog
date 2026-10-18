import json
import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from labcatalog import defaults
from labcatalog.config import PrepareStep
from labcatalog.datalad.annex import is_placeholder
from labcatalog.datalad.bridge import run_args
from labcatalog.exceptions import DataladError, PrepareBusyError
from labcatalog.metadata.accepted import who
from labcatalog.own_python import folder_for
from labcatalog.paths import expand_path
from labcatalog.processes import NEW_GROUP, end_tree
from labcatalog.project import Project

Status = Literal["up to date", "outdated", "missing output", "missing input"]

# A shell that starts its own process group can be stopped together with what it runs.


@dataclass
class FileState:
    path: str
    resolved: Path
    modified: datetime | None
    placeholder: bool = False


@dataclass
class StepState:
    step: PrepareStep
    inputs: list[FileState]
    outputs: list[FileState]
    status: Status


@dataclass
class Runner:
    by: str
    since: datetime


@dataclass
class StepRun:
    name: str
    command: str
    log: list[str] = field(default_factory=list)
    exit_code: int | None = None
    stopped: bool = False

    @property
    def outcome(self) -> str:
        if self.stopped:
            return "stopped"
        if self.exit_code is None:
            return "running"
        return "succeeded" if self.exit_code == 0 else f"failed (exit code {self.exit_code})"


@dataclass
class Session:
    # Each step's last run, kept while the window is open.
    runs: dict[str, StepRun] = field(default_factory=dict)
    current: str | None = None
    process: subprocess.Popen | None = None
    stopping: bool = False


def step_states(project: Project) -> list[StepState]:
    return [step_state(project, step) for step in project.config.prepare]


def step_state(project: Project, step: PrepareStep) -> StepState:
    inputs = [file_state(project.root, path) for path in step.inputs]
    outputs = [file_state(project.root, path) for path in step.outputs]
    return StepState(step, inputs, outputs, status_of(inputs, outputs))


def file_state(root: Path, path: str) -> FileState:
    resolved = expand_path(path, root)
    if is_placeholder(resolved):
        return FileState(path, resolved, None, placeholder=True)
    modified = datetime.fromtimestamp(resolved.stat().st_mtime) if resolved.exists() else None
    return FileState(path, resolved, modified)


def status_of(inputs: list[FileState], outputs: list[FileState]) -> Status:
    if any(f.modified is None for f in inputs):
        return "missing input"
    if any(f.modified is None for f in outputs):
        return "missing output"
    if inputs and max(f.modified for f in inputs) > min(f.modified for f in outputs):
        return "outdated"
    return "up to date"


def run_steps(
    project: Project,
    names: list[str],
    session: Session,
    outdated_only: bool = False,
    echo: Callable[[str], None] | None = None,
    rscript: str | None = None,
    datalad: str | None = None,
    anyway: bool = False,
    python: str | None = None,
) -> list[StepRun]:
    if project.config.prepare_with != "datalad":
        datalad = None
    elif not datalad:
        raise DataladError(
            "The prepare steps run with DataLad (prepare_with: datalad); "
            "set the path to datalad on the Settings page"
        )
    session.stopping = False
    done = []
    try:
        with prepare_lock(project.root, anyway):
            for step in project.config.prepare:
                if session.stopping:
                    break
                # Checked step by step, so a rerun step makes the steps after it outdated too.
                if step.name not in names or (
                    outdated_only and step_state(project, step).status == "up to date"
                ):
                    continue
                run = StepRun(step.name, step.run)
                session.runs[step.name] = run
                done.append(run)
                if echo:
                    echo(f"== {step.name}: {step.run}")
                execute(step, project.root, run, session, echo, rscript, datalad, python)
                if run.exit_code != 0:
                    break
    finally:
        session.current = None
    return done


@contextmanager
def prepare_lock(root: Path, anyway: bool = False) -> Iterator[None]:
    lock = root / defaults.PREPARE_LOCK_FILENAME
    # Two people running the steps at once would write the same files.
    if not anyway and (other := running(root)):
        raise PrepareBusyError(other.by, other.since, lock)
    lock.write_text(
        json.dumps({"by": who(root), "since": datetime.now().isoformat(timespec="seconds")}),
        encoding="utf-8",
    )
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def running(root: Path) -> Runner | None:
    path = root / defaults.PREPARE_LOCK_FILENAME
    if not path.is_file():
        return None
    found = json.loads(path.read_text(encoding="utf-8"))
    return Runner(found["by"], datetime.fromisoformat(found["since"]))


def execute(
    step: PrepareStep,
    root: Path,
    run: StepRun,
    session: Session,
    echo: Callable[[str], None] | None,
    rscript: str | None,
    datalad: str | None,
    python: str | None = None,
) -> None:
    session.current = step.name
    process = subprocess.Popen(
        run_args(step, root, datalad) if datalad else step.run,
        shell=not datalad,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=environment(rscript, python),
        **NEW_GROUP,
    )
    session.process = process
    for line in process.stdout:
        run.log.append(line.rstrip("\r\n"))
        if echo:
            echo(run.log[-1])
    run.exit_code = process.wait()
    run.stopped = session.stopping
    session.process = None


def environment(rscript: str | None, python: str | None = None) -> dict[str, str] | None:
    # A step can then call Rscript and python by name and get the ones the Settings page chose.
    first = [str(Path(rscript).parent)] if rscript else []
    if python:
        first.append(str(folder_for(python)))
    if not first:
        return None
    return {**os.environ, "PATH": os.pathsep.join([*first, os.environ.get("PATH", "")])}


def stop(session: Session) -> None:
    session.stopping = True
    process = session.process
    if process is None:
        return
    end_tree(process)
