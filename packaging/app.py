import multiprocessing

from labcatalog.gui import launch

if __name__ == "__main__":
    # The native window runs in a child process; a frozen app must dispatch it here.
    multiprocessing.freeze_support()
    launch()
