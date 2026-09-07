"""Tests for driving interactive REPLs through pexpect.replwrap."""

import os
import re
import unittest
from pathlib import Path
from unittest import mock

import pytest

import pexpect
from pexpect import replwrap

pytestmark = pytest.mark.usefixtures("fast_sleep", "lean_child_env", "killed_pty_children")

skip_pypy = "This test fails on PyPy because of REPL differences"


class REPLWrapTestBase(unittest.TestCase):
    """Base class that pins the prompt of any shell the tests spawn."""

    def setUp(self) -> None:
        """Pin PS1 and PS2 so a spawned shell has a predictable prompt."""
        super().setUp()
        self.save_ps1 = os.getenv("PS1", r"\$")
        self.save_ps2 = os.getenv("PS2", ">")
        os.putenv("PS1", r"\$")
        os.putenv("PS2", ">")

    def tearDown(self) -> None:
        """Put back the PS1 and PS2 values saved by setUp."""
        super().tearDown()
        os.putenv("PS1", self.save_ps1)
        os.putenv("PS2", self.save_ps2)


class REPLWrapTestCase(REPLWrapTestBase):
    """Tests for the bash, zsh and Python REPL wrappers."""

    def test_bash(self) -> None:
        """Run a command in bash, and reject empty input."""
        bash = replwrap.bash()
        res = bash.run_command("alias xyzzy=true; alias")
        assert "alias" in res, res

        try:
            bash.run_command("")
        except ValueError:
            pass
        else:
            msg = "Didn't raise ValueError for empty input"
            raise AssertionError(msg)

    def test_bash_env(self) -> None:
        """env, which displays PS1=..., should not mess up finding the prompt."""
        bash = replwrap.bash()
        res = bash.run_command("export PS1")
        res = bash.run_command("env")
        assert "PS1" in res
        res = bash.run_command("echo $HOME")
        assert res.startswith("/"), res

    def test_multiline(self) -> None:
        """Run a multi-line command, and recover the REPL after incomplete input."""
        bash = replwrap.bash()
        res = bash.run_command("echo '1 2\n3 4'")
        assert res.strip().splitlines() == ["1 2", "3 4"]

        # Should raise ValueError if input is incomplete
        try:
            bash.run_command("echo '5 6")
        except ValueError:
            pass
        else:
            msg = "Didn't raise ValueError for incomplete input"
            raise AssertionError(msg)

        # Check that the REPL was reset (SIGINT) after the incomplete input
        res = bash.run_command("echo '1 2\n3 4'")
        assert res.strip().splitlines() == ["1 2", "3 4"]

    def test_existing_spawn(self) -> None:
        """Wrap a shell the caller spawned instead of one replwrap starts.

        Given a bash spawned by the caller with the bundled rcfile, so that the
        prompt is predictable whatever the host bash configuration is,
        When it is handed to :class:`replwrap.REPLWrapper` as an existing spawn,
        Then the wrapper adopts it and runs commands through it.
        """
        bashrc = Path(replwrap.__file__).parent / "bashrc.sh"
        child = pexpect.spawn("bash", ["--rcfile", str(bashrc)], timeout=5, encoding="utf-8")
        repl = replwrap.REPLWrapper(
            child, re.compile("[$#]"), "PS1='{0}' PS2='{1}' PROMPT_COMMAND=''"
        )

        print(repl)
        res = repl.run_command("echo $HOME")
        print(res)
        assert res.startswith("/"), res

    def test_zsh_reports_a_missing_shell(self) -> None:
        """Report a zsh binary that is not on the path.

        Given a command name that names no executable on the path, so that the
        test does not depend on zsh being installed,
        When :func:`replwrap.zsh` is asked to start it,
        Then :exc:`pexpect.ExceptionPexpect` is raised.
        """
        # A name that matches nothing is the one lookup that walks every PATH
        # entry, so point PATH at a single directory to keep the cost of the
        # test off the length of the developer's PATH.
        with (
            mock.patch.dict(os.environ, {"PATH": str(Path(__file__).parent)}),
            pytest.raises(pexpect.ExceptionPexpect),
        ):
            replwrap.zsh(command="zsh-does-not-exist")


if __name__ == "__main__":
    unittest.main()
