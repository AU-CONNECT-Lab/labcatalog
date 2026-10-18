import shutil
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
