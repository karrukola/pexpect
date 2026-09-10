"""Nox sessions used to lint and test the pexpect project."""

from __future__ import annotations

import sys
from pathlib import Path

import nox

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

# The coverage floor for a Windows run, which cannot be the 100% in
# pyproject.toml because it cannot run the whole suite: pexpect's pty API does
# not exist there, and tests/conftest.py drops the two thirds of the suite that
# drives it. What is left reaches this, so the floor still catches a Windows
# regression -- it just has to be re-tuned whenever a module moves across that
# POSIX/Windows line, which is a thing a reviewer can see in the same diff.
_WINDOWS_COVERAGE_FLOOR = 46


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
    # One report per interpreter. The five lint sessions would otherwise take turns
    # overwriting a single reports/mypy.xml, which CI publishes as an artifact and
    # would then publish only the last of.
    session.run(
        "mypy",
        "--junit-xml",
        f"reports/mypy-{session.python}.xml",
        _SRC_ROOT,
        _TESTS_ROOT,
    )


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
    if sys.platform == "win32":
        # A subset of the library ran, so a subset's floor; see
        # _WINDOWS_COVERAGE_FLOOR.
        report_args: tuple[str, ...] = (f"--fail-under={_WINDOWS_COVERAGE_FLOOR}",)
    else:
        # src/pexpect/_winpty.py is the Windows process backend. It imports
        # `winpty`, which exists only on Windows and cannot be installed here,
        # so a POSIX run cannot execute a line of it and 100% is a statement
        # about the rest. The Windows run measures it without this.
        report_args = ("--omit=*/pexpect/_winpty.py",)
    # report.fail_under makes both of these exit 2 once the total has slipped, and
    # each writes its report before it checks. Tolerating that one exit code on the
    # HTML run -- 2 is the floor, 1 is a real error -- leaves the failing to the XML
    # run below, so a run that breaks the floor still publishes the report that
    # shows where it broke. CI uploads both.
    session.run("coverage", "html", *report_args, success_codes=(0, 2))
    session.run("coverage", "xml", *report_args)
