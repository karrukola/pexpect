#!/usr/bin/env python
"""PEXPECT LICENSE.

This license is approved by the OSI and FSF as GPL-compatible.
http://opensource.org/licenses/isc-license.txt

Copyright (c) 2012, Noah Spurrier <noah@noah.org>
PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE THIS SOFTWARE FOR ANY
PURPOSE WITH OR WITHOUT FEE IS HEREBY GRANTED, PROVIDED THAT THE ABOVE
COPYRIGHT NOTICE AND THIS PERMISSION NOTICE APPEAR IN ALL COPIES.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""

import sys
import unittest

import pytest

import pexpect

from . import pexpect_test_case

if sys.platform != "win32":
    from ptyprocess import ptyprocess

    ptyprocess._make_eof_intr()

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")


def byte(i: int) -> bytes:
    """Return the single byte whose ordinal is ``i``."""
    return bytes([i])


class TestCtrlChars(pexpect_test_case.PexpectTestCase):
    """Send control characters to a child that reports the ordinal it read."""

    def setUp(self) -> None:
        """Point every test at the getch.py helper script."""
        super().setUp()
        self.getch_cmd = self.PYTHONBIN + " getch.py"

    def spawn_getch(self) -> pexpect.spawn:
        """Spawn getch.py without the pause pexpect takes before each send.

        These tests send one byte at a time and read the report back before
        sending the next, so expect() already paces the child; the send delay
        would only add a pause per byte to the longest tests in the suite.
        """
        child = pexpect.spawn(self.getch_cmd, echo=False, timeout=5)
        child.delaybeforesend = None
        return child

    def test_control_chars(self) -> None:
        """Send all 256 8-bit byte values to a child process."""
        child = self.spawn_getch()
        child.expect("READY")
        # Send the whole range in one write and then read the reports back. One
        # write per byte costs 255 pty round trips, which is by itself more than
        # the time budget of a test; the ordinals still have to come back in
        # order, so every value is checked either way.
        child.send(b"".join(byte(i) for i in range(1, 256)))
        for i in range(1, 256):
            child.expect(f"{i}<STOP>")

        # This needs to be last, as getch.py exits on \x00
        child.send(byte(0))
        child.expect("0<STOP>")
        child.expect(pexpect.EOF)
        assert not child.isalive()
        assert child.exitstatus == 0

    def test_sendintr(self) -> None:
        """Send the interrupt character and see the child read it."""
        child = self.spawn_getch()
        child.expect("READY")
        child.sendintr()
        child.expect(str(ord(ptyprocess._INTR)) + "<STOP>")

        child.send(byte(0))
        child.expect("0<STOP>")
        child.expect(pexpect.EOF)
        assert not child.isalive()
        assert child.exitstatus == 0

    def test_sendeof(self) -> None:
        """Send the EOF character and see the child read it."""
        child = self.spawn_getch()
        child.expect("READY")
        child.sendeof()
        child.expect(str(ord(ptyprocess._EOF)) + "<STOP>")

        child.send(byte(0))
        child.expect("0<STOP>")
        child.expect(pexpect.EOF)
        assert not child.isalive()
        assert child.exitstatus == 0

    def test_bad_sendcontrol_chars(self) -> None:
        """Return 0 from sendcontrol() for a character that is not a control."""
        child = self.spawn_getch()
        child.expect("READY")
        assert child.sendcontrol("1") == 0

    def test_sendcontrol(self) -> None:
        """Send every control code that sendcontrol() knows by name."""
        child = self.spawn_getch()
        child.expect("READY")
        for ctrl in "abcdefghijklmnopqrstuvwxyz":
            assert child.sendcontrol(ctrl) == 1
            val = ord(ctrl) - ord("a") + 1
            child.expect_exact(str(val) + "<STOP>")

        # escape character
        assert child.sendcontrol("[") == 1
        child.expect("27<STOP>")
        assert child.sendcontrol("\\") == 1
        child.expect("28<STOP>")
        # telnet escape character
        assert child.sendcontrol("]") == 1
        child.expect("29<STOP>")
        assert child.sendcontrol("^") == 1
        child.expect("30<STOP>")
        # irc protocol uses this to underline ...
        assert child.sendcontrol("_") == 1
        child.expect("31<STOP>")
        # the real "backspace is delete"
        assert child.sendcontrol("?") == 1
        child.expect("127<STOP>")

        # NUL, same as ctrl + ' '
        assert child.sendcontrol("@") == 1
        child.expect("0<STOP>")
        child.expect(pexpect.EOF)
        assert not child.isalive()
        assert child.exitstatus == 0


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(TestCtrlChars)
