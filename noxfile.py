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
# pyproject.toml because it cannot run the whole suite: tests/integration and
# the four modules that drive POSIX programs skip themselves there, and
# interact() cannot run at all. What is left reaches this, so the floor still
# catches a Windows regression -- it just has to be re-tuned whenever a module
# moves across that line, which is a thing a reviewer can see in the same diff.
#
# 46 is stale. It was measured before pexpect.spawn ran on Windows at all, when
# nearly the whole suite dropped out at collection time (see tests/conftest.py
# and tests/test_unsupported.py's git history) rather than the handful of
# modules and individual tests that skip themselves now. Far more of the suite
# runs on Windows today, so this floor no longer catches much -- it must be
# raised to the figure the first Windows CI run of this change reports, which
# `collate_coverage` prints before it checks the floor.
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
    # Both platforms, because the library carries live code for both: the
    # process backend behind pexpect._ptyproc is ptyprocess on POSIX and
    # pywinpty on Windows, and whichever platform mypy assumes, the other one's
    # branch drops out of the analysis.
    #
    # The win32 pass covers src/ only. The suite's POSIX-only modules reach for
    # os.fork, signal.SIGHUP and signal.SIGKILL at the top level of a function,
    # guarded by a pytest skipif that mypy cannot read, so a win32 pass over
    # tests/ would report a few dozen attr-defined errors about tests that
    # never run there. What the second pass is for is the library's Windows
    # code, and src/ is where all of it lives.
    #
    # One report per interpreter per platform -- the sessions would otherwise
    # take turns overwriting one reports/mypy.xml, which CI publishes.
    for platform, targets in (("linux", (_SRC_ROOT, _TESTS_ROOT)), ("win32", (_SRC_ROOT,))):
        session.run(
            "mypy",
            f"--platform={platform}",
            "--junit-xml",
            f"reports/mypy-{session.python}-{platform}.xml",
            *targets,
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
