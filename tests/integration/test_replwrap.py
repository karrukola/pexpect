"""Tests for :mod:`pexpect.replwrap` that drive a real REPL.

Two things put a test in here rather than in ``tests/test_replwrap.py``, and
both are about the machine rather than about pexpect.

The first is cost. Reading a formatted man page, waiting out a command that
sleeps, and starting Python's own interactive shell each take more than the
per-test budget out there, whatever pexpect does around them.

``test_recovers_when_no_prompt_follows_the_signal`` is here on cost too,
though what it waits out is inside replwrap: the one-second timeout
``run_command`` allows for a prompt after the SIGINT it sends.

The second is that a shell is not something this repository ships. zsh is
frequently absent, so ``test_zsh`` skips itself when it is; bash is effectively
everywhere, but its prompt and its startup files belong to the host, and a test
that reaches a prompt is at the mercy of both. ``replwrap`` goes to some length
to neutralise that -- it forces PS1 and hands bash its own rcfile -- and these
tests are what checks that it succeeds.
"""

import platform
import re
import shutil
import sys
import unittest
from pathlib import Path

import pytest

import pexpect
from pexpect import replwrap
from tests.utils import no_editor_repl

pytestmark = pytest.mark.usefixtures("fast_sleep", "lean_child_env")

skip_pypy = "This test fails on PyPy because of REPL differences"


class REPLWrapIntegrationTestCase(unittest.TestCase):
    """Tests whose cost, or whose configuration, is the REPL rather than replwrap."""

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

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_zsh_recovers_from_incomplete_input(self) -> None:
        """Reject incomplete input on a real zsh and leave the REPL usable.

        zsh runs with its line editor off, so it does not act on the SIGINT
        run_command sends until it next reads from the terminal. Until that was
        handled this raised TIMEOUT after the full timeout instead of
        ValueError, and no test noticed: the zsh test covered only the
        empty-input branch, which never reaches a shell.
        """
        zsh = replwrap.zsh()
        with pytest.raises(ValueError, match="input was incomplete"):
            zsh.run_command("echo '5 6")
        assert zsh.run_command("echo done").strip() == "done"

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


class REPLWrapEnvironmentTestCase(unittest.TestCase):
    """Tests for what environment ``replwrap.python()`` hands its child.

    See issues.md entry 35. ``REPLWrapper.__init__`` used to replace the
    child's environment outright (``env={"NO_COLOR": "1"}``) rather than add
    to it, so a REPL started from a command string ran with no ``PATH``, no
    ``HOME`` and no locale. The fix is ``env={**os.environ, "NO_COLOR": "1",
    "TERM": "dumb"}`` -- both halves matter and this class checks both:
    inheriting the parent's variables, and pinning ``TERM`` so a 3.13+ Python
    does not rebuild its full-screen editor and wrap every reply in escape
    sequences.

    ``lean_child_env`` sets ``PYTHON_BASIC_REPL=1`` for every test in this
    module, which would hide a broken ``TERM`` here too, so this test undoes
    that one variable to be able to fail.
    """

    @pytest.fixture(autouse=True)
    def _monkeypatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch

    def test_python_inherits_parent_environment(self) -> None:
        """A parent-set variable reaches the child, and output comes back clean.

        Given a variable set in this process's environment and
        ``PYTHON_BASIC_REPL`` unset, so the real REPL editor is in play,
        When ``replwrap.python()`` starts a REPL and it is asked to print
        that variable,
        Then the value comes back, and it is not wrapped in the escape
        sequences a full-screen editor would add if ``TERM`` were left
        pointing at a real terminal.
        """
        if platform.python_implementation() == "PyPy":
            raise unittest.SkipTest(skip_pypy)

        self.monkeypatch.delenv("PYTHON_BASIC_REPL", raising=False)
        self.monkeypatch.setenv("PEXPECT_REPLWRAP_TEST_MARKER", "canary")

        p = replwrap.python()
        res = p.run_command("import os; print(os.environ.get('PEXPECT_REPLWRAP_TEST_MARKER'))")
        assert res.strip() == "canary", res
        assert "\x1b" not in res, res


class REPLWrapInterruptTestCase(unittest.TestCase):
    """Tests for recovering a REPL after it is handed incomplete input."""

    def test_recovers_when_no_prompt_follows_the_signal(self) -> None:
        """Reject incomplete input on a REPL that ignores SIGINT until it reads.

        Given a REPL that records SIGINT and acts on it only at its next read,
        which is what zsh does with its line editor off,
        When run_command submits a command the REPL treats as incomplete,
        Then ValueError is raised and the REPL is still usable afterwards.
        """
        repl = no_editor_repl()
        with pytest.raises(ValueError, match="input was incomplete"):
            repl.run_command("keep going\\")
        assert repl.run_command("done").strip() == "DONE"


if __name__ == "__main__":
    unittest.main()
