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

import os
import unittest
from pathlib import Path

import pytest

import pexpect
from pexpect import fdpexpect

from . import pexpect_test_case


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for fdspawn() on a plain file descriptor."""

    def setUp(self) -> None:
        """Announce the test id, then run the shared set-up."""
        print(self.id())
        pexpect_test_case.PexpectTestCase.setUp(self)

    def test_fd(self) -> None:
        """Read a file through fdspawn() until EOF."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = fdpexpect.fdspawn(fd)
        s.expect(b"This is the end of test data:")
        s.expect(pexpect.EOF)
        assert s.before == b" END\n"

    def test_maxread(self) -> None:
        """Match across reads when maxread is smaller than the file."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = fdpexpect.fdspawn(fd)
        s.maxread = 100
        s.expect("2")
        s.expect("This is the end of test data:")
        s.expect(pexpect.EOF)
        assert s.before == b" END\n"

    def test_fd_isalive(self) -> None:
        """Report isalive() as false once the descriptor is closed."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = fdpexpect.fdspawn(fd)
        assert s.isalive()
        os.close(fd)
        assert not s.isalive(), "Should not be alive after close()"

    def test_fd_isatty(self) -> None:
        """Report isatty() as false for a regular file."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = fdpexpect.fdspawn(fd)
        assert not s.isatty()
        s.close()

    def test_fileobj(self) -> None:
        """Accept a file object and take its descriptor from it."""
        f = Path("TESTDATA.txt").open()  # noqa: SIM115  # fdspawn takes ownership of the fd
        s = fdpexpect.fdspawn(f)  # Should get the fileno from the file handle
        s.expect("2")
        s.close()
        assert not s.isalive()
        s.close()  # Smoketest - should be able to call this again

    def test_write_and_writelines(self) -> None:
        """Send data to a file descriptor with the file-like write methods.

        Given a pipe whose write end is wrapped in an fdspawn,
        When :meth:`fdspawn.write`, :meth:`fdspawn.sendline` and
        :meth:`fdspawn.writelines` are used to send data,
        Then everything sent, including the line separator sendline appends,
        arrives at the read end of the pipe in order.
        """
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        s = fdpexpect.fdspawn(write_fd)

        s.write(b"one")
        s.writelines([b"two", b"three"])
        sent = s.sendline(b"four")
        assert sent == len(b"four" + s.linesep)

        expected = b"onetwothreefour" + s.linesep
        assert os.read(read_fd, len(expected)) == expected
        s.close()

    def test_read_nonblocking_with_the_default_timeout(self) -> None:
        """Read with the timeout the spawn was created with.

        Given an fdspawn over a file, created with a timeout of its own,
        When :meth:`fdspawn.read_nonblocking` is called without a timeout, so
        that the spawn timeout applies,
        Then the requested number of bytes is returned.
        """
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = fdpexpect.fdspawn(fd, timeout=10)
        assert s.read_nonblocking(size=4) == b"This"
        s.close()

    def test_read_nonblocking_with_poll(self) -> None:
        """Wait for the file descriptor with poll() instead of select().

        Given an fdspawn over a file, created with use_poll set,
        When :meth:`fdspawn.read_nonblocking` is called,
        Then poll() reports the descriptor ready and the bytes are returned.
        """
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = fdpexpect.fdspawn(fd, use_poll=True)
        assert s.read_nonblocking(size=4) == b"This"
        s.close()

    def test_read_nonblocking_times_out(self) -> None:
        """Give up on a file descriptor that never becomes readable.

        Given an fdspawn over the read end of a pipe that nothing writes to,
        When :meth:`fdspawn.read_nonblocking` is called with a short timeout,
        Then :exc:`pexpect.TIMEOUT` is raised.
        """
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, write_fd)
        s = fdpexpect.fdspawn(read_fd)

        with pytest.raises(pexpect.TIMEOUT):
            s.read_nonblocking(size=1, timeout=0.1)
        s.close()


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
