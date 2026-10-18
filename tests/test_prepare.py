import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from labcatalog.cli import main
from labcatalog.data.prepare import Session, run_steps, step_states, stop
from labcatalog.pipeline import run_catalog, run_check, run_validate
from labcatalog.project import init_project, load_project

PYTHON = json.dumps(f'"{sys.executable}"')[1:-1]
CLEAN = """\
from pathlib import Path
rows = Path("raw/a.csv").read_text().splitlines()
Path("data/a.csv").write_text("\\n".join(rows) + "\\n")
print(f"cleaned {len(rows) - 1} rows")
"""
SUMMARIZE = """\
from pathlib import Path
Path("data/b.txt").write_text(str(len(Path("data/a.csv").read_text().splitlines())))
"""
STEPS = f"""
prepare:
  - name: clean
    run: "{PYTHON} scripts/clean.py"
    inputs: [raw/a.csv, scripts/clean.py]
    outputs: [data/a.csv]
  - name: summarize
    run: "{PYTHON} scripts/summarize.py"
    inputs: [data/a.csv]
    outputs: [data/b.txt]
"""


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    root = init_project(tmp_path / "lab", example=False)
    with (root / "labcatalog.yaml").open("a", encoding="utf-8") as file:
        file.write(STEPS)
    (root / "raw").mkdir()
    (root / "raw" / "a.csv").write_text("id,x\n1,2\n2,3\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "clean.py").write_text(CLEAN, encoding="utf-8")
    (root / "scripts" / "summarize.py").write_text(SUMMARIZE, encoding="utf-8")
    return root


def statuses(root: Path) -> list[str]:
    return [state.status for state in step_states(load_project(root))]


def set_time(path: Path, seconds: float) -> None:
    os.utime(path, (seconds, seconds))


def test_steps_run_in_order_and_rerun_only_what_is_outdated(project_root):
    assert statuses(project_root) == ["missing output", "missing input"]
    session = Session()
    runs = run_steps(load_project(project_root), ["clean", "summarize"], session)
    assert [(r.name, r.outcome) for r in runs] == [
        ("clean", "succeeded"),
        ("summarize", "succeeded"),
    ]
    assert session.runs["clean"].log == ["cleaned 2 rows"]
    assert statuses(project_root) == ["up to date", "up to date"]

    hour_ago = time.time() - 3600
    for path in ("data/a.csv", "data/b.txt", "scripts/clean.py", "scripts/summarize.py"):
        set_time(project_root / path, hour_ago)
    (project_root / "raw" / "a.csv").write_text("id,x\n1,2\n", encoding="utf-8")
    assert statuses(project_root) == ["outdated", "up to date"]
    runs = run_steps(
        load_project(project_root), ["clean", "summarize"], session, outdated_only=True
    )
    assert [r.name for r in runs] == ["clean", "summarize"]
    assert (project_root / "data" / "b.txt").read_text(encoding="utf-8") == "2"
    assert run_steps(load_project(project_root), ["clean", "summarize"], session, True) == []


def test_a_failing_step_stops_the_rest(project_root):
    (project_root / "scripts" / "clean.py").write_text(
        "import sys\nprint('raw file is locked')\nsys.exit(3)\n", encoding="utf-8"
    )
    runs = run_steps(load_project(project_root), ["clean", "summarize"], Session())
    assert [(r.name, r.outcome, r.log) for r in runs] == [
        ("clean", "failed (exit code 3)", ["raw file is locked"])
    ]


def test_steps_find_the_rscript_folder_first_on_path(project_root, tmp_path):
    (project_root / "scripts" / "clean.py").write_text(
        "import os\nprint(os.environ['PATH'].split(os.pathsep)[0])\n", encoding="utf-8"
    )
    rscript = tmp_path / "R" / "bin" / "Rscript.exe"
    session = Session()
    run_steps(load_project(project_root), ["clean"], session, rscript=str(rscript))
    assert session.runs["clean"].log == [str(rscript.parent)]
    assert os.environ["PATH"].split(os.pathsep)[0] != str(rscript.parent)


def test_stop_ends_the_running_command(project_root):
    (project_root / "scripts" / "clean.py").write_text(
        "import time\nprint('started', flush=True)\ntime.sleep(60)\n", encoding="utf-8"
    )
    session = Session()
    worker = threading.Thread(
        target=run_steps, args=(load_project(project_root), ["clean", "summarize"], session)
    )
    worker.start()
    deadline = time.time() + 20
    while "clean" not in session.runs or not session.runs["clean"].log:
        assert time.time() < deadline
        time.sleep(0.05)
    stop(session)
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert session.runs["clean"].outcome == "stopped"
    assert "summarize" not in session.runs


def test_check_warns_about_missing_and_outdated_outputs(project_root):
    warnings = [(i.code, i.message) for i in run_check(project_root).issues]
    assert warnings == [
        ("prepare_output_missing", "prepare step clean: data/a.csv does not exist; run the step"),
        (
            "prepare_output_missing",
            "prepare step summarize: data/b.txt does not exist; run the step",
        ),
    ]
    run_steps(load_project(project_root), ["clean", "summarize"], Session())
    set_time(project_root / "data" / "b.txt", time.time() - 3600)
    [issue] = run_check(project_root).issues
    assert issue.level == "warning"
    assert (
        issue.message
        == "prepare step summarize: data/b.txt is older than data/a.csv; run the step again"
    )


def test_manifest_records_the_inputs(project_root):
    run_steps(load_project(project_root), ["clean", "summarize"], Session())
    inputs = run_catalog(project_root).manifest.inputs
    assert [(r.step, r.path) for r in inputs] == [
        ("clean", "raw/a.csv"),
        ("clean", "scripts/clean.py"),
        ("summarize", "data/a.csv"),
    ]
    assert all(len(r.sha256) == 64 for r in inputs)


def test_step_names_are_unique_and_steps_need_outputs(project_root):
    config = project_root / "labcatalog.yaml"
    text = config.read_text(encoding="utf-8").replace("name: summarize", "name: clean")
    config.write_text(text.replace("outputs: [data/b.txt]", "outputs: []"), encoding="utf-8")
    assert [i.message for i in run_validate(project_root)] == [
        "prepare: step name 'clean' is used more than once",
        "prepare[2] (clean).outputs: list at least one file the step writes",
    ]


def test_example_steps_rebuild_the_example_data(mock_project, tmp_path):
    steps = load_project(mock_project).config.prepare
    assert len(steps) == 21
    for step in steps:
        _, script, export, clean = step.run.split()
        out = tmp_path / Path(clean).name
        subprocess.run(
            [sys.executable, script, export, str(out)],
            cwd=mock_project,
            check=True,
            capture_output=True,
        )
        assert out.read_text(encoding="utf-8") == (mock_project / clean).read_text(
            encoding="utf-8"
        ), step.name


def test_cli_runs_every_step_and_reports_a_failure(project_root, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["labcatalog", "prepare", "-p", str(project_root)])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("== clean: ")
    assert out[1] == "cleaned 2 rows"
    assert out[-1] == "2 step(s) succeeded."

    (project_root / "scripts" / "summarize.py").write_text(
        "raise SystemExit(2)\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 1
    assert capsys.readouterr().err.strip() == "Step summarize failed (exit code 2)."
