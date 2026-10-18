import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest

from labcatalog.gui import shared


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(shared, "PROJECTS", {})


def test_windows_on_one_project_share_its_catalog_until_a_file_changes(mock_project):
    times, first = shared.catalog(mock_project)
    assert shared.catalog(mock_project)[1] is first
    config = mock_project / "labcatalog.yaml"
    later = os.stat(config).st_mtime_ns + 10**9
    os.utime(config, ns=(later, later))
    changed_times, again = shared.catalog(mock_project)
    assert again is not first and changed_times != times


def test_a_fit_runs_once_for_every_window_and_each_choice(mock_project):
    _, result = shared.catalog(mock_project)
    runs = []

    def fit(found, rscript, estimator):
        runs.append((estimator, rscript))
        return [estimator]

    with ThreadPoolExecutor(4) as pool:
        found = list(
            pool.map(lambda _: shared.fitted(partial(fit, estimator="ml"), result, None), range(4))
        )
    assert found == [["ml"]] * 4 and runs == [("ml", None)]
    assert shared.fitted(partial(fit, estimator="mlr"), result, None) == ["mlr"]
    assert shared.fitted(partial(fit, estimator="ml"), result, "Rscript") == ["ml"]
    assert len(runs) == 3


def test_a_failed_fit_is_tried_again(mock_project):
    _, result = shared.catalog(mock_project)
    tries = []

    def fit(found, rscript, estimator):
        tries.append(1)
        if len(tries) == 1:
            raise RuntimeError("R stopped")
        return ["done"]

    with pytest.raises(RuntimeError):
        shared.fitted(partial(fit, estimator="ml"), result, None)
    assert shared.fitted(partial(fit, estimator="ml"), result, None) == ["done"]
