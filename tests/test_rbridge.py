import shutil
import subprocess
import sys
import threading
import time
from glob import glob

import pytest

from labcatalog.exceptions import RError
from labcatalog.stats import rbridge


def rscript() -> str | None:
    return shutil.which("Rscript") or next(
        iter(glob("C:/Program Files/R/R-*/bin/Rscript.exe")), None
    )


@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_closing_the_window_ends_the_r_still_running():
    failed = []

    def fit() -> None:
        try:
            rbridge.run_r(rscript(), ["-e", "Sys.sleep(60)"])
        except RError as err:
            failed.append(err)

    thread = threading.Thread(target=fit)
    started = time.monotonic()
    thread.start()
    while not rbridge.RUNNING:
        time.sleep(0.05)
    [process] = rbridge.RUNNING
    rbridge.stop_all()
    thread.join(timeout=20)
    assert not thread.is_alive() and time.monotonic() - started < 20
    assert failed and process.poll() is not None and not rbridge.RUNNING


@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_analyses_past_the_limit_wait_their_turn(monkeypatch):
    monkeypatch.setattr(rbridge, "turns", rbridge.turns)
    rbridge.allow_at_once(1)
    most = []

    def watch() -> None:
        while len(most) < 200:
            most.append(len(rbridge.RUNNING))
            time.sleep(0.02)

    watcher = threading.Thread(target=watch)
    watcher.start()
    runs = [
        threading.Thread(target=rbridge.run_r, args=(rscript(), ["-e", "Sys.sleep(1)"]))
        for _ in range(3)
    ]
    for run in runs:
        run.start()
    for run in runs:
        run.join(timeout=60)
    watcher.join()
    assert max(most) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
@pytest.mark.skipif(rscript() is None, reason="R is not installed")
def test_killing_labcatalog_ends_the_r_it_started(tmp_path):
    written = tmp_path / "written.txt"
    late = f"Sys.sleep(3); writeLines('late', '{written.as_posix()}')"
    starter = (
        "import sys\n"
        "from labcatalog.stats import rbridge\n"
        "rbridge.run_process([sys.argv[1], '-e', sys.argv[2]], "
        "started=lambda p: print(p.pid, flush=True))\n"
    )
    server = subprocess.Popen(
        [sys.executable, "-c", starter, rscript(), late], stdout=subprocess.PIPE, text=True
    )
    assert server.stdout.readline().strip()
    # /F without /T, as a crash or Task Manager ends only labcatalog itself.
    subprocess.run(["taskkill", "/F", "/PID", str(server.pid)], capture_output=True, check=True)
    server.wait(timeout=10)
    time.sleep(6)
    assert not written.exists()
