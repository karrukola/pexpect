"""Pytest configuration for the tests that are allowed to take real time."""

from __future__ import annotations

import pathlib

import coverage
import pytest

# Per-test budget in this directory, in seconds. Generous on purpose: it is here
# to catch a test that hangs, not to pace one that works.
_TIMEOUT = 60

_HERE = pathlib.Path(__file__).parent

# Where the run was started. Read while this conftest is imported, which is
# before any test chdirs into tests/: a relative data file in the coverage
# config is relative to where coverage started, not to wherever a test has since
# moved to.
_INVOCATION_DIR = pathlib.Path.cwd()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Lift the suite's per-test time budget for every test in this directory."""
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(pytest.mark.timeout(_TIMEOUT))


@pytest.fixture
def child_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Extend an already-measured run into the Python children a module spawns.

    ``tests/interact.py`` runs pexpect code of its own, so the lines it covers
    only show up if the child starts coverage as well. Coverage does that when it
    finds COVERAGE_PROCESS_START in the environment, and pays a full coverage
    startup for it: about 80 ms per child, which is why only this directory
    offers this.

    Whether to measure at all stays with the caller. ``coverage run -m pytest``
    leaves a live Coverage object behind, so this passes the same config and data
    file on to the children; a plain ``pytest`` leaves none and the children run
    unmeasured. Both the config path and the data file come from that object
    rather than being named here, so ``--rcfile`` and COVERAGE_FILE reach the
    children too.
    """
    current = coverage.Coverage.current()
    if current is None or not current.config.config_file:
        return
    monkeypatch.setenv("COVERAGE_PROCESS_START", current.config.config_file)
    monkeypatch.setenv("COVERAGE_FILE", str(_INVOCATION_DIR / current.config.data_file))
