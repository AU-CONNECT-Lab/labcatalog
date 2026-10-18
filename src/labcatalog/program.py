import multiprocessing
import sys

from labcatalog import own_python


def main() -> None:
    # The Windows program's entry: called with --python it runs a script and does nothing else.
    if sys.argv[1:2] == [own_python.FLAG]:
        sys.exit(own_python.main(sys.argv[2:]))
    from labcatalog.gui import launch

    # The native window runs in a child process; a frozen app must dispatch it here.
    multiprocessing.freeze_support()
    launch()
