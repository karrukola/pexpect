"""Helpers shared by the test modules and the programs they spawn."""

import os


def no_coverage_env() -> dict[str, str]:
    """Return a copy of os.environ that won't trigger coverage measurement."""
    env = os.environ.copy()
    env.pop("COV_CORE_SOURCE", None)
    return env
