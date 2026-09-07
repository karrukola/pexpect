"""Tests for :mod:`pexpect.replwrap` that need a REPL to do real work.

Reading a formatted man page, waiting out a command that sleeps, and starting
Python's own interactive shell each cost more than the suite's time budget on
their own, whatever pexpect does around them.
"""

import platform
import shutil
import sys
import unittest

import pytest

import pexpect
from pexpect import replwrap
from tests.test_replwrap import REPLWrapTestBase, skip_pypy

pytestmark = pytest.mark.usefixtures("fast_sleep", "lean_child_env")


class REPLWrapIntegrationTestCase(REPLWrapTestBase):
    """REPL tests whose cost is the REPL, not replwrap."""

    def test_pager_as_cat(self) -> None:
        """PAGER is set to cat, to prevent timeout in ``man sleep``."""
        bash = replwrap.bash()
        res = bash.run_command("man sleep", timeout=5)
        assert "SLEEP" in res.upper(), res

    def test_long_running_multiline(self) -> None:
        """Ensure the default timeout is used for multi-line commands."""
        bash = replwrap.bash()
        res = bash.run_command("echo begin\r\nsleep 2\r\necho done")
        assert res.strip().splitlines() == ["begin", "done"]

    def test_long_running_continuation(self) -> None:
        """Also ensure timeout when used within continuation prompts."""
        bash = replwrap.bash()
        # The two extra '\\' in the following expression force a continuation
        # prompt:
        # $ echo begin\
        #     + ;
        # $ sleep 2
        # $ echo done
        res = bash.run_command("echo begin\\\n;sleep 2\r\necho done")
        assert res.strip().splitlines() == ["begin", "done"]

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_zsh(self) -> None:
        """Run a command in zsh, and reject empty input."""
        zsh = replwrap.zsh()
        res = zsh.run_command("env")
        assert "PAGER" in res, res

        try:
            zsh.run_command("")
        except ValueError:
            pass
        else:
            msg = "Didn't raise ValueError for empty input"
            raise AssertionError(msg)

    def test_python(self) -> None:
        """Run single- and multi-line statements in a Python REPL."""
        if platform.python_implementation() == "PyPy":
            raise unittest.SkipTest(skip_pypy)

        p = replwrap.python()
        res = p.run_command("4+7")
        assert res.strip() == "11"

        res = p.run_command("for a in range(3): print(a)\n")
        assert res.strip().splitlines() == ["0", "1", "2"]

    def test_no_change_prompt(self) -> None:
        """Wrap a Python REPL without changing its prompt."""
        if platform.python_implementation() == "PyPy":
            raise unittest.SkipTest(skip_pypy)

        child = pexpect.spawn(
            sys.executable, echo=False, timeout=5, encoding="utf-8", env={"NO_COLOR": "1"}
        )
        # prompt_change=None should mean no prompt change
        py = replwrap.REPLWrapper(child, ">>> ", prompt_change=None, continuation_prompt="... ")
        assert py.prompt == ">>> "

        res = py.run_command("for a in range(3): print(a)\n")
        assert res.strip().splitlines() == ["0", "1", "2"]


if __name__ == "__main__":
    unittest.main()
