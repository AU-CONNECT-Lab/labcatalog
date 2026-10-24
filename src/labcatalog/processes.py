import contextlib
import ctypes
import os
import signal
import subprocess
import sys
from ctypes import wintypes

# A process started in its own group can be ended together with what it starts.
NEW_GROUP: dict = {} if sys.platform == "win32" else {"start_new_session": True}
JOB_EXTENDED_LIMITS = 9
KILL_ON_JOB_CLOSE = 0x2000
# Windows closes this handle however labcatalog ends, even when killed, and so ends the job.
job: int | None = None


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time", ctypes.c_int64),
        ("per_job_user_time", ctypes.c_int64),
        ("limit_flags", wintypes.DWORD),
        ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimits),
        ("io_counters", ctypes.c_uint64 * 6),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


def end_with_labcatalog(process: subprocess.Popen) -> None:
    # Elsewhere a stopped server ends its processes on shutdown; a killed one cannot.
    global job
    if sys.platform != "win32":
        return
    kernel = ctypes.windll.kernel32
    if job is None:
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel.CreateJobObjectW(None, None)
        limits = ExtendedLimits()
        limits.basic.limit_flags = KILL_ON_JOB_CLOSE
        kernel.SetInformationJobObject(
            wintypes.HANDLE(job), JOB_EXTENDED_LIMITS, ctypes.byref(limits), ctypes.sizeof(limits)
        )
    kernel.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(process._handle))


def end_tree(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        # /T also ends what the process started, such as Rscript's R or a shell's command.
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
