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

import socket
import unittest
from pathlib import Path

import pexpect
from pexpect import socket_pexpect

from . import pexpect_test_case


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
        s.expect(b"This is the end of test data:")
        s.expect(pexpect.EOF)
        assert s.before == b" END\n"

    def test_maxread(self) -> None:
        """Match across reads when maxread is smaller than the available data."""
        socket = open_file_socket("TESTDATA.txt")
        s = socket_pexpect.SocketSpawn(socket)
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


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
