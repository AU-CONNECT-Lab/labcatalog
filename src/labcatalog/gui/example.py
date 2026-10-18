import shutil
from pathlib import Path

from labcatalog import defaults
from labcatalog.gui import preferences
from labcatalog.project import init_project


def example_folder() -> Path:
    return preferences.folder() / "example"


def example_copy() -> Path:
    # The window's own copy, so trying the Set up page never changes the installed package.
    folder = example_folder()
    if not folder.exists():
        init_project(folder)
    return folder


def reset_example() -> Path:
    if example_folder().exists():
        shutil.rmtree(example_folder())
    return example_copy()


def start_folder() -> Path:
    # The project open when the window last closed, or the example the first time.
    last = preferences.mine().get(preferences.LAST_PROJECT)
    if last and (Path(last) / defaults.CONFIG_FILENAME).is_file():
        return Path(last)
    return example_copy()
