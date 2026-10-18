import contextlib
import os
import runpy
import sys
import tempfile
import traceback
from pathlib import Path

# The Windows program has no python.exe; called with this flag it runs a script as Python would.
FLAG = "--python"
SHIM = "labcatalog_python"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def command(program: str) -> list[str]:
    own = frozen() and Path(program) == Path(sys.executable)
    return [program, FLAG] if own else [program]


def folder_for(program: str) -> Path:
    # The folder to put first on PATH, so a step that calls python gets this one.
    if not (frozen() and Path(program) == Path(sys.executable)):
        return Path(program).parent
    shim = Path(tempfile.gettempdir()) / SHIM
    shim.mkdir(exist_ok=True)
    line = f'@"{sys.executable}" {FLAG} %*\n'
    for name in ("python.cmd", "python3.cmd"):
        (shim / name).write_text(line, encoding="utf-8")
    return shim


def main(argv: list[str]) -> int:
    # Takes the options the program itself passes (-I, -X utf8, -u), then -c code or a script.
    streams()
    args = list(argv)
    while args and args[0] in ("-I", "-u", "-X"):
        flag = args.pop(0)
        if flag == "-X" and args:
            args.pop(0)
    if not args:
        print("labcatalog --python needs a script or -c code", file=sys.stderr)
        return 2
    try:
        if args[0] == "-c":
            sys.argv = ["-c", *args[2:]]
            exec(compile(args[1], "<string>", "exec"), {"__name__": "__main__"})
        else:
            sys.argv = args
            sys.path.insert(0, str(Path(args[0]).resolve().parent))
            runpy.run_path(args[0], run_name="__main__")
    except SystemExit as stop:
        return exit_code(stop.code)
    except BaseException:
        traceback.print_exc()
        return 1
    finally:
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.flush()
    return 0


def exit_code(code: object) -> int:
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=sys.stderr)
    return 1


def streams() -> None:
    # A program built without a console has no sys.stdout; the pipes the caller gave are still there.
    for name, number in (("stdin", -10), ("stdout", -11), ("stderr", -12)):
        if getattr(sys, name) is not None:
            continue
        with contextlib.suppress(OSError, ValueError):
            setattr(sys, name, std_handle(number, "r" if name == "stdin" else "w"))


def std_handle(number: int, mode: str):
    import ctypes
    import msvcrt

    handle = ctypes.windll.kernel32.GetStdHandle(number)
    if handle in (0, -1, None):
        raise OSError("no handle")
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY if mode == "r" else 0)
    return open(fd, mode, encoding="utf-8", errors="replace", closefd=False)
