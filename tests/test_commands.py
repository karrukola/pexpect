"""Spawn each of commands.py's stand-ins and check what it produces.

Every other module in this suite drives commands.CAT/TRUE/echo()/sleep()
incidentally, as a way to test some pexpect behaviour. Nothing tests the
stand-ins themselves, so on Windows their first real run would be the CI leg.
This module is that check, kept small on purpose: one test per stand-in.
"""

import pytest

import pexpect

from . import commands, pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")
# the program cat(1) may display ^D\x08\x08 when \x04 (EOF, Ctrl-D) is sent
_CAT_EOF = b"^D\x08\x08"


class TestCaseCommands(pexpect_test_case.PexpectTestCase):
    """One test per name commands.py exports."""

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
