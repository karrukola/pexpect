"""Nox sessions used to lint the pexpect project."""

from __future__ import annotations

import os
from pathlib import Path

import nox

# ref: https://nox.thea.codes/en/stable/usage.html#opt-error-on-missing-interpreters
_ON_CI = os.getenv("CI") is not None


nox.options.error_on_external_run = True
nox.options.default_venv_backend = "uv"


_REPO_ROOT = Path(__file__).parent

_PYTHON_VERSIONS = [
    "3.10",
    "3.11",
    "3.12",
    "3.13",
    "3.14",
]


def _install_deps(session: nox.Session) -> None:
    session.run_install(
        "uv",
        "sync",
        "-q",
        f"--python={session.virtualenv.location}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )


@nox.session(python=_PYTHON_VERSIONS)
def lint(session: nox.Session) -> None:
    """Autoformat and type check the project."""
    _install_deps(session)
    session.run("ruff", "format", "--check", _REPO_ROOT)
    session.run("ruff", "check", _REPO_ROOT)
