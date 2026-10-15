import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from labcatalog.config import PrepareStep
from labcatalog.paths import expand_path
from labcatalog.project import Project

Status = Literal["up to date", "outdated", "missing output", "missing input"]

# A shell that starts its own process group can be stopped together with what it runs.
NEW_GROUP: dict = {} if sys.platform == "win32" else {"start_new_session": True}


@dataclass
class FileState:
    path: str
    resolved: Path
    modified: datetime | None


@dataclass
class StepState:
    step: PrepareStep
    inputs: list[FileState]
    outputs: list[FileState]
    status: Status


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
) -> list[StepRun]:
    session.stopping = False
    done = []
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
        execute(step, project.root, run, session, echo, rscript)
        if run.exit_code != 0:
            break
    session.current = None
    return done


def execute(
    step: PrepareStep,
    root: Path,
    run: StepRun,
    session: Session,
    echo: Callable[[str], None] | None,
    rscript: str | None,
) -> None:
    session.current = step.name
    process = subprocess.Popen(
        step.run,
        shell=True,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=environment(rscript),
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


def environment(rscript: str | None) -> dict[str, str] | None:
    if not rscript:
        return None
    # A step can then call Rscript by name and get the R chosen on the Settings page.
    path = os.pathsep.join([str(Path(rscript).parent), os.environ.get("PATH", "")])
    return {**os.environ, "PATH": path}


def stop(session: Session) -> None:
    session.stopping = True
    process = session.process
    if process is None:
        return
    if sys.platform == "win32":
        # /T also ends what the shell started, such as Rscript.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
