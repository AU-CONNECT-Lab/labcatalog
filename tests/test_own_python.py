import os
import subprocess
import sys
from pathlib import Path

from labcatalog import own_python
from labcatalog.data.prepare import environment

RUNNER = "import sys; from labcatalog.own_python import main; sys.exit(main(sys.argv[1:]))"


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    # As the Windows program would be called: its own flags, then a script or -c code.
    return subprocess.run(
        [sys.executable, "-c", RUNNER, *args], cwd=cwd, capture_output=True, text=True
    )


def test_a_script_runs_with_its_arguments_beside_its_folder(tmp_path):
    (tmp_path / "helper.py").write_text("NAME = 'helper'\n", encoding="utf-8")
    (tmp_path / "script.py").write_text(
        "import sys\nimport helper\nprint(helper.NAME, sys.argv[1:], __name__)\n"
        "open(sys.argv[2], 'w').write('done')\n",
        encoding="utf-8",
    )
    done = run("-I", "-X", "utf8", "script.py", "a", "out.txt", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "helper ['a', 'out.txt'] __main__"
    assert (tmp_path / "out.txt").read_text() == "done"


def test_code_errors_and_exits_end_as_python_would(tmp_path):
    assert run("-I", "-c", "print(1 + 1)", cwd=tmp_path).stdout.strip() == "2"
    failed = run("-c", "raise ValueError('bad')", cwd=tmp_path)
    assert failed.returncode == 1 and "ValueError: bad" in failed.stderr
    assert run("-c", "import sys; sys.exit(3)", cwd=tmp_path).returncode == 3
    stopped = run("-c", "import sys; sys.exit('stopped')", cwd=tmp_path)
    assert stopped.returncode == 1 and "stopped" in stopped.stderr
    assert run(cwd=tmp_path).returncode == 2


def test_the_program_calls_itself_with_the_flag_only_when_frozen(monkeypatch, tmp_path):
    assert own_python.command(sys.executable) == [sys.executable]
    assert own_python.folder_for(sys.executable) == Path(sys.executable).parent
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    monkeypatch.setattr("tempfile.tempdir", None)
    assert own_python.command(sys.executable) == [sys.executable, own_python.FLAG]
    assert own_python.command("C:/Python/python.exe") == ["C:/Python/python.exe"]
    shim = own_python.folder_for(sys.executable)
    assert shim.parent == tmp_path
    assert (shim / "python.cmd").read_text() == f'@"{sys.executable}" --python %*\n'
    path = environment(None, sys.executable)["PATH"]
    assert path.split(os.pathsep)[0] == str(shim)


def test_a_steps_path_starts_with_the_chosen_r_and_python():
    path = environment("C:/R/bin/Rscript.exe", sys.executable)["PATH"].split(os.pathsep)
    assert path[:2] == [str(Path("C:/R/bin")), str(Path(sys.executable).parent)]
    assert environment(None, None) is None
