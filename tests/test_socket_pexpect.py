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

import io
import socket
import unittest
from pathlib import Path

import pytest

import pexpect
from pexpect import socket_pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep")


def open_file_socket(filename: str) -> socket.socket:
    """Return a socket whose read end is preloaded with the contents of *filename*."""
    read_socket, write_socket = socket.socketpair()
    write_socket.sendall(Path(filename).read_bytes())
    write_socket.close()
    return read_socket


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Exercise SocketSpawn against a socket holding a canned file."""

    def setUp(self) -> None:
        """Announce the test being run, then set up the usual pexpect fixture."""
        print(self.id())
        pexpect_test_case.PexpectTestCase.setUp(self)

    def test_socket(self) -> None:
        """Match a pattern and then EOF on data read from a socket."""
        socket = open_file_socket("TESTDATA.txt")
        s = socket_pexpect.SocketSpawn(socket)
        self.addCleanup(s.close)
        s.expect(b"This is the end of test data:")
        s.expect(pexpect.EOF)
        assert s.before == b" END\n"

    def test_maxread(self) -> None:
        """Match across reads when maxread is smaller than the available data."""
        socket = open_file_socket("TESTDATA.txt")
        s = socket_pexpect.SocketSpawn(socket)
        self.addCleanup(s.close)
        s.maxread = 100
        s.expect("2")
        s.expect("This is the end of test data:")
        s.expect(pexpect.EOF)
        assert s.before == b" END\n"

    def test_socket_isalive(self) -> None:
        """A SocketSpawn is alive until close() is called."""
        socket = open_file_socket("TESTDATA.txt")
        s = socket_pexpect.SocketSpawn(socket)
        assert s.isalive()
        s.close()
        assert not s.isalive(), "Should not be alive after close()"

    def test_socket_isatty(self) -> None:
        """A socket is not a tty."""
        socket = open_file_socket("TESTDATA.txt")
        s = socket_pexpect.SocketSpawn(socket)
        assert not s.isatty()
        s.close()

    def test_write_and_writelines(self) -> None:
        """Send data to a socket with the file-like write methods.

        Given a socket pair whose first socket is wrapped in a SocketSpawn,
        When :meth:`SocketSpawn.write`, :meth:`SocketSpawn.sendline` and
        :meth:`SocketSpawn.writelines` are used to send data,
        Then everything sent, including the line separator sendline appends,
        arrives at the other end of the socket pair in order.
        """
        send_socket, recv_socket = socket.socketpair()
        self.addCleanup(recv_socket.close)
        s = socket_pexpect.SocketSpawn(send_socket)

        s.write(b"one")
        s.writelines([b"two", b"three"])
        sent = s.sendline(b"four")
        assert sent == len(b"four" + s.linesep)

        expected = b"onetwothreefour" + s.linesep
        assert recv_socket.recv(len(expected)) == expected
        s.close()

    def test_read_nonblocking_with_the_default_timeout(self) -> None:
        """Read with the timeout the spawn was created with.

        Given a SocketSpawn over a socket holding canned data, created with a
        timeout of its own,
        When :meth:`SocketSpawn.read_nonblocking` is called without a timeout,
        so that the spawn timeout applies,
        Then the requested number of bytes is returned.
        """
        s = socket_pexpect.SocketSpawn(open_file_socket("TESTDATA.txt"), timeout=10)
        assert s.read_nonblocking(size=4) == b"This"
        s.close()

    def test_close_is_repeatable(self) -> None:
        """Close a SocketSpawn twice without raising.

        Given a SocketSpawn that has already been closed,
        When :meth:`SocketSpawn.close` is called again,
        Then the call does nothing and the spawn stays closed.
        """
        s = socket_pexpect.SocketSpawn(open_file_socket("TESTDATA.txt"))
        s.close()
        s.close()
        assert s.closed

    def test_read_nonblocking_logs_to_logfile(self) -> None:
        """Data read from the socket reaches ``logfile``.

        Given a SocketSpawn with a binary ``logfile``, over a socket that
        will receive data from its peer,
        When :meth:`SocketSpawn.expect` matches data sent over the socket,
        Then that data has been written to ``logfile``.
        """
        send_socket, recv_socket = socket.socketpair()
        self.addCleanup(send_socket.close)
        self.addCleanup(recv_socket.close)
        logfile = io.BytesIO()
        s = socket_pexpect.SocketSpawn(recv_socket, timeout=3, logfile=logfile)
        self.addCleanup(s.close)

        send_socket.sendall(b"hello world")
        s.expect(b"hello")

        assert b"hello" in logfile.getvalue()

    def test_read_nonblocking_logs_to_logfile_read(self) -> None:
        """Data read from the socket reaches ``logfile_read``.

        Given a SocketSpawn with a binary ``logfile_read``, over a socket
        that will receive data from its peer,
        When :meth:`SocketSpawn.expect` matches data sent over the socket,
        Then that data has been written to ``logfile_read``.
        """
        send_socket, recv_socket = socket.socketpair()
        self.addCleanup(send_socket.close)
        self.addCleanup(recv_socket.close)
        logfile_read = io.BytesIO()
        s = socket_pexpect.SocketSpawn(recv_socket, timeout=3)
        s.logfile_read = logfile_read
        self.addCleanup(s.close)

        send_socket.sendall(b"hello world")
        s.expect(b"hello")

        assert b"hello" in logfile_read.getvalue()

    def test_expect_with_zero_timeout_raises_pexpect_timeout(self) -> None:
        """``expect(..., timeout=0)`` raises TIMEOUT, not BlockingIOError.

        Given a SocketSpawn over a socket with nothing waiting to be read,
        When :meth:`SocketSpawn.expect` is called with ``timeout=0`` (poll),
        Then :class:`pexpect.TIMEOUT` is raised rather than the underlying
        ``BlockingIOError`` that a non-blocking socket recv raises.
        """
        send_socket, recv_socket = socket.socketpair()
        self.addCleanup(send_socket.close)
        self.addCleanup(recv_socket.close)
        s = socket_pexpect.SocketSpawn(recv_socket, timeout=3)
        self.addCleanup(s.close)

        with pytest.raises(pexpect.TIMEOUT):
            s.expect(b"x", timeout=0)

    def test_read_nonblocking_with_zero_timeout_raises_pexpect_timeout(self) -> None:
        """``read_nonblocking(size, 0)`` raises TIMEOUT, not BlockingIOError.

        Given a SocketSpawn over a socket with nothing waiting to be read,
        When :meth:`SocketSpawn.read_nonblocking` is called directly with a
        timeout of 0 (poll),
        Then :class:`pexpect.TIMEOUT` is raised rather than the underlying
        ``BlockingIOError`` that a non-blocking socket recv raises.
        """
        send_socket, recv_socket = socket.socketpair()
        self.addCleanup(send_socket.close)
        self.addCleanup(recv_socket.close)
        s = socket_pexpect.SocketSpawn(recv_socket, timeout=3)
        self.addCleanup(s.close)

        with pytest.raises(pexpect.TIMEOUT):
            s.read_nonblocking(1, 0)


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
