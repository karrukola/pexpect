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

import tempfile
import unittest

import pytest

import pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")
# the program cat(1) may display ^D\x08\x08 when \x04 (EOF, Ctrl-D) is sent
_CAT_EOF = b"^D\x08\x08"


class TestCaseLog(pexpect_test_case.PexpectTestCase):
    """Check what pexpect writes to logfile, logfile_read and logfile_send."""

    def test_log(self) -> None:
        """Everything read from the child lands in the logfile."""
        log_message = "This is a test."
        with tempfile.NamedTemporaryFile() as mylog:
            p = pexpect.spawn("echo", [log_message])
            p.logfile = mylog
            p.expect(pexpect.EOF)
            p.logfile = None
            mylog.seek(0)
            lf = mylog.read()
        assert lf.rstrip() == log_message.encode("ascii")

    def test_log_logfile_read(self) -> None:
        """logfile_read records what the child echoes back, not what we sent."""
        log_message = "This is a test."
        with tempfile.NamedTemporaryFile() as mylog:
            p = pexpect.spawn("cat")
            p.logfile_read = mylog
            p.sendline(log_message)
            p.sendeof()
            p.expect(pexpect.EOF)
            p.logfile = None
            mylog.seek(0)
            lf = mylog.read()
        lf = lf.replace(_CAT_EOF, b"")
        assert lf == b"This is a test.\r\nThis is a test.\r\n"

    def test_log_logfile_send(self) -> None:
        """logfile_send records what we sent to the child, not what came back."""
        log_message = b"This is a test."
        with tempfile.NamedTemporaryFile() as mylog:
            p = pexpect.spawn("cat")
            p.logfile_send = mylog
            p.sendline(log_message)
            p.sendeof()
            p.expect(pexpect.EOF)
            p.logfile = None
            mylog.seek(0)
            lf = mylog.read()
        lf = lf.replace(b"\x04", b"")
        assert lf.rstrip() == log_message

    def test_log_send_and_received(self) -> None:
        """Log the test message three times.

        Once for the data we sent, once for the data that cat echoes back as
        characters are typed, and once for the data that cat prints after we
        send a linefeed (sent by sendline).
        """
        log_message = "This is a test."
        with tempfile.NamedTemporaryFile() as mylog:
            p = pexpect.spawn("cat")
            p.logfile = mylog
            p.sendline(log_message)
            p.sendeof()
            p.expect(pexpect.EOF)
            p.logfile = None
            mylog.seek(0)
            lf = mylog.read()
        lf = lf.replace(b"\x04", b"").replace(_CAT_EOF, b"")
        assert lf == b"This is a test.\nThis is a test.\r\nThis is a test.\r\n"


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(TestCaseLog)
