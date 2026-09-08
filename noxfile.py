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
_SRC_ROOT = _REPO_ROOT / "src"
_TESTS_ROOT = _REPO_ROOT / "tests"

# The interpreter matrix, and the only copy of it: the workflow names sessions, never
# versions, so adding one is an edit to this file alone. uv reads the filename
# natively -- `uv python install` with no arguments installs exactly these -- so one
# command sets a fresh checkout up to run the whole matrix, and the uv backend below
# fetches whatever is still missing when a session asks for it.
_PYTHON_VERSIONS = (_REPO_ROOT / ".python-versions").read_text(encoding="utf-8").split()


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
    session.run("mypy", "--junit-xml", "reports/mypy.xml", _SRC_ROOT, _TESTS_ROOT)


@nox.session
def coverage_clean(session: nox.Session) -> None:
    """Clean coverage data."""
    _install_deps(session)
    session.run("coverage", "erase")


@nox.session(python=_PYTHON_VERSIONS, requires=("coverage_clean",))
def test(session: nox.Session) -> None:
    """Run project tests."""
    _install_deps(session)
    session.run("coverage", "run", "-m", "pytest", _TESTS_ROOT)

    session.notify("collate_coverage")


@nox.session
def collate_coverage(session: nox.Session) -> None:
    """Combine test coverage results from all test executions."""
    _install_deps(session)
    session.run("coverage", "combine")
    session.run("coverage", "xml")
    session.run("coverage", "html")
