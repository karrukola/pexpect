"""Spawn each of commands.py's stand-ins and check what it produces.

Every other module in this suite drives commands.CAT/TRUE/echo()/sleep()
incidentally, as a way to test some pexpect behaviour. Nothing tests the
stand-ins themselves, and commands.py dispatches on platform, so on Linux
commands.CAT and friends resolve to the native cat/true/echo/sleep -- the
Python stand-ins under tests/helpers/ never run at all here, and on Windows
their first execution would be the CI leg nobody watching this checkout can
see. The second test per name below drives the stand-in script directly,
through commands._helper(), regardless of platform, so a broken loop or a
syntax error in one fails here rather than only on a CI run this machine
cannot reach.
"""

import sys

import pytest

import pexpect

from . import commands, pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")

# spawn(echo=False) raises ExceptionPexpect on Windows, because ConPTY keeps
# echo in the child's own console host where the parent cannot reach it. The
# two tests that drive cat need it: cat copies its input back, and with echo
# on the assertion would see every line twice. What the stand-in does under a
# console is a question for a machine with one.
_NEEDS_ECHO_CONTROL = pytest.mark.skipif(
    sys.platform == "win32",
    reason="needs echo control: spawn(echo=False) is refused",
)
# the program cat(1) may display ^D\x08\x08 when \x04 (EOF, Ctrl-D) is sent
_CAT_EOF = b"^D\x08\x08"


class TestCaseCommands(pexpect_test_case.PexpectTestCase):
    """One test per name commands.py exports."""

    @_NEEDS_ECHO_CONTROL
    def test_cat_copies_stdin_to_stdout(self) -> None:
        """CAT echoes back a line sent to it, until EOF."""
        p = pexpect.spawn(commands.CAT, echo=False)
        p.sendline("abc")
        p.sendeof()
        p.expect(pexpect.EOF)
        assert isinstance(p.before, bytes)
        assert p.before.replace(_CAT_EOF, b"") == b"abc\r\n"

    def test_true_exits_clean(self) -> None:
        """TRUE exits immediately with status 0."""
        p = pexpect.spawn(commands.TRUE)
        p.expect(pexpect.EOF)
        assert p.wait() == 0
        assert not p.isalive()

    def test_echo_prints_its_argument(self) -> None:
        """echo() prints the given text, joined back together, then a newline."""
        p = pexpect.spawn(commands.echo("alpha beta"))
        p.expect(pexpect.EOF)
        assert p.before == b"alpha beta\r\n"

    def test_sleep_keeps_the_child_alive_for_the_given_time(self) -> None:
        """sleep() keeps the child alive until it exits cleanly on its own."""
        p = pexpect.spawn(commands.sleep(0.05))
        assert p.isalive()
        assert p.wait() == 0
        assert not p.isalive()

    @_NEEDS_ECHO_CONTROL
    def test_cat_py_copies_stdin_to_stdout(self) -> None:
        """The cat.py stand-in, driven directly, echoes back a line until EOF."""
        p = pexpect.spawn(commands._helper("cat.py"), echo=False)
        p.sendline("abc")
        p.sendeof()
        p.expect(pexpect.EOF)
        assert isinstance(p.before, bytes)
        assert p.before.replace(_CAT_EOF, b"") == b"abc\r\n"

    def test_true_py_exits_clean(self) -> None:
        """The true.py stand-in, driven directly, exits immediately with status 0."""
        p = pexpect.spawn(commands._helper("true.py"))
        p.expect(pexpect.EOF)
        assert p.wait() == 0
        assert not p.isalive()

    def test_echo_py_prints_its_arguments(self) -> None:
        """The echo.py stand-in, driven directly, prints its arguments and a newline."""
        p = pexpect.spawn(f"{commands._helper('echo.py')} alpha beta")
        p.expect(pexpect.EOF)
        assert p.before == b"alpha beta\r\n"

    def test_sleep_py_keeps_the_child_alive_for_the_given_time(self) -> None:
        """The sleep.py stand-in, driven directly, keeps the child alive until it exits."""
        p = pexpect.spawn(f"{commands._helper('sleep.py')} 0.05")
        assert p.isalive()
        assert p.wait() == 0
        assert not p.isalive()
