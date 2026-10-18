import contextlib
import os
import signal
import subprocess
import sys

# A process started in its own group can be ended together with what it starts.
NEW_GROUP: dict = {} if sys.platform == "win32" else {"start_new_session": True}


def end_tree(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # /T also ends what the process started, such as Rscript's R or a shell's command.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
