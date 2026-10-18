import multiprocessing
import sys

if __name__ == "__main__":
    # Called with --python, the program runs a script with its own Python and does nothing else.
    if sys.argv[1:2] == ["--python"]:
        from labcatalog.own_python import main

        sys.exit(main(sys.argv[2:]))
    from labcatalog.gui import launch

    # The native window runs in a child process; a frozen app must dispatch it here.
    multiprocessing.freeze_support()
    launch()
