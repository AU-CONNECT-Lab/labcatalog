import threading
from collections import defaultdict
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from labcatalog.data.manifest import file_times
from labcatalog.pipeline import CatalogResult, run_catalog


@dataclass
class Shared:
    # One project as its files stood, for every window that shows it.
    times: dict[Path, int]
    result: CatalogResult
    fits: dict[tuple, Any] = field(default_factory=dict)
    locks: defaultdict[tuple, threading.Lock] = field(
        default_factory=lambda: defaultdict(threading.Lock)
    )


PROJECTS: dict[Path, Shared] = {}
LOCKS: defaultdict[Path, threading.Lock] = defaultdict(threading.Lock)


def catalog(root: Path) -> tuple[dict[Path, int], CatalogResult]:
    # A second window waits for the first one's build instead of making its own.
    with LOCKS[root]:
        # Taken first, so a save while the catalog builds still shows as a change.
        times = file_times(root)
        found = PROJECTS.get(root)
        if found is None or found.times != times:
            found = Shared(times, run_catalog(root))
            PROJECTS[root] = found
        return found.times, found.result


def fitted(function: partial, result: CatalogResult, rscript: str | None) -> Any:
    # One fit per catalog and choice of estimator and R; a failed fit is tried again next time.
    shared = next((s for s in PROJECTS.values() if s.result is result), None)
    if shared is None:
        return function(result, rscript)
    key = (function.func.__name__, tuple(sorted(function.keywords.items())), rscript)
    with shared.locks[key]:
        if key not in shared.fits:
            shared.fits[key] = function(result, rscript)
        return shared.fits[key]
