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

import errno
import multiprocessing
import os
import signal
import socket
import sys
import unittest
from typing import TYPE_CHECKING

import pytest

import pexpect
from pexpect import socket_pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep")

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event

# Python 3.14 changed the non-macOS POSIX default to forkserver
# but the code in this module does not work with it
# See https://github.com/python/cpython/issues/125714
if multiprocessing.get_start_method() == "forkserver":
    mp_context = multiprocessing.get_context(method="fork")
else:
    mp_context = multiprocessing.get_context()


class SocketServerError(Exception):
    """The test socket server did not come up in time."""


# Timeout handed to the sessions of the tests that wait for a TIMEOUT to be
# raised. Every test in this suite runs under a time budget, so the wait for a read
# that never completes has to stay well below it.
_READ_TIMEOUT = 0.02

# Upper bound on how long a subprocess may take to reach the state the test
# waits for. Only reached when something is broken, so it can stay generous.
_STARTUP_TIMEOUT = 10.0


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Exercise SocketSpawn against a local socket server run in a subprocess."""

    def setUp(self) -> None:
        """Start the socket server subprocess and wait for it to listen."""
        print(self.id())
        pexpect_test_case.PexpectTestCase.setUp(self)
        self.af = socket.AF_INET
        self.host = "127.0.0.1"
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except OSError:
            try:
                socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                self.af = socket.AF_INET6
                self.host = "::1"
            except OSError:
                pass
        self.port = 49152 + 10000
        self.motd = (
            b"""\
------------------------------------------------------------------------------
*                  Welcome to the SOCKET UNIT TEST code!                     *
------------------------------------------------------------------------------
*                                                                            *
* This unit test code is our best effort at testing the ability of the       *
* pexpect library to handle sockets. We need some text to test buffer size   *
* handling.                                                                  *
*                                                                            *
* A page is 1024 bytes or 1K. 80 x 24 = 1920. So a standard terminal window  *
* contains more than one page. We actually want more than a page for our     *
* tests.                                                                     *
*                                                                            *
* This is the twelfth line, and we need 24. So we need a few more paragraphs.*
* We can keep them short and just put lines between them.                    *
*                                                                            *
* The 80 x 24 terminal size comes from the ancient past when computers were  *
* only able to display text in cuneiform writing.                            *
*                                                                            *
* The cunieform writing system used the edge of a reed to make marks on clay *
* tablets.                                                                   *
*                                                                            *
* It was the forerunner of the style of handwriting used by doctors to write *
* prescriptions. Thus the name: pre (before) script (writing) ion (charged   *
* particle).                                                                 *
------------------------------------------------------------------------------
""".replace(b"\n", b"\n\r")
            + b"\r\n"
        )
        self.prompt1 = b"Press Return to continue:"
        self.prompt2 = b"Rate this unit test>"
        self.prompt3 = b"Press X to exit:"
        self.enter = b"\r\n"
        self.exit = b"X\r\n"
        self.server_up = mp_context.Event()
        self.server_process = mp_context.Process(target=self.socket_server, args=(self.server_up,))
        self.server_process.daemon = True
        self.server_process.start()
        if not self.server_up.wait(timeout=_STARTUP_TIMEOUT):
            msg = "Could not start socket server"
            raise SocketServerError(msg)

    def tearDown(self) -> None:
        """Interrupt the socket server subprocess and reap it."""
        os.kill(self.server_process.pid, signal.SIGINT)
        self.server_process.join(timeout=5.0)
        pexpect_test_case.PexpectTestCase.tearDown(self)

    def socket_server(self, server_up: "Event") -> None:
        """Serve the canned motd and prompts until interrupted; runs in a subprocess."""
        sock = None
        try:
            sock = socket.socket(self.af, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(5)
            server_up.set()
            while True:
                (conn, _addr) = sock.accept()
                conn.send(self.motd)
                conn.send(self.prompt1)
                result = conn.recv(1024)
                if result != self.enter:
                    break
                conn.send(self.prompt2)
                result = conn.recv(1024)
                if result != self.enter:
                    break
                conn.send(self.prompt3)
                result = conn.recv(1024)
                if result.startswith(self.exit[:1]):
                    conn.shutdown(socket.SHUT_RDWR)
                    conn.close()
        except KeyboardInterrupt:
            pass
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
            except OSError:
                pass
        sys.exit(0)

    def spawn(
        self, sock: socket.socket, timeout: float = 30, *, use_poll: bool = False
    ) -> socket_pexpect.SocketSpawn:
        """Override me with other ways of spawning on a socket."""
        return socket_pexpect.SocketSpawn(sock, timeout=timeout, use_poll=use_poll)

    def socket_fn(self, timed_out: "Event", all_read: "Event") -> None:
        """Read everything the server sent, then time out on a second read.

        Runs in a subprocess and exits with ETIMEDOUT once the timeout is seen.
        """
        result = 0
        try:
            sock = socket.socket(self.af, socket.SOCK_STREAM)
            sock.connect((self.host, self.port))
            session = self.spawn(sock, timeout=_READ_TIMEOUT)
            # Get all data from server
            session.read_nonblocking(size=4096)
            all_read.set()
            # This read should timeout
            session.read_nonblocking(size=4096)
        except pexpect.TIMEOUT:
            timed_out.set()
            result = errno.ETIMEDOUT
        sys.exit(result)

    def test_socket(self) -> None:
        """Walk the whole prompt sequence with send() and end at EOF."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        session.expect(self.prompt1)
        assert session.before == self.motd
        session.send(self.enter)
        session.expect(self.prompt2)
        session.send(self.enter)
        session.expect(self.prompt3)
        session.send(self.exit)
        session.expect(pexpect.EOF)
        assert session.before == b""

    def test_socket_with_write(self) -> None:
        """write() drives the prompt sequence just as send() does."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        session.expect(self.prompt1)
        assert session.before == self.motd
        session.write(self.enter)
        session.expect(self.prompt2)
        session.write(self.enter)
        session.expect(self.prompt3)
        session.write(self.exit)
        session.expect(pexpect.EOF)
        assert session.before == b""

    def test_timeout(self) -> None:
        """Expecting a pattern the server never sends raises TIMEOUT."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=_READ_TIMEOUT)
        with pytest.raises(pexpect.TIMEOUT):
            session.expect(b"Bogus response")

    def test_interrupt(self) -> None:
        """A signal arriving mid-read is retried, and the read still times out."""
        timed_out = mp_context.Event()
        all_read = mp_context.Event()
        test_proc = mp_context.Process(target=self.socket_fn, args=(timed_out, all_read))
        test_proc.daemon = True
        test_proc.start()
        all_read.wait(timeout=_STARTUP_TIMEOUT)
        os.kill(test_proc.pid, signal.SIGWINCH)
        timed_out.wait(timeout=_STARTUP_TIMEOUT)
        test_proc.join(timeout=5.0)
        assert test_proc.exitcode == errno.ETIMEDOUT

    def test_multiple_interrupts(self) -> None:
        """Repeated signals during a read are all retried, and it still times out."""
        timed_out = mp_context.Event()
        all_read = mp_context.Event()
        test_proc = mp_context.Process(target=self.socket_fn, args=(timed_out, all_read))
        test_proc.daemon = True
        test_proc.start()
        all_read.wait(timeout=_STARTUP_TIMEOUT)
        while not timed_out.is_set():
            os.kill(test_proc.pid, signal.SIGWINCH)
            # Event.wait paces the signals with real time and returns as soon as
            # the child reports the timeout it was interrupted out of.
            timed_out.wait(timeout=0.001)
        test_proc.join(timeout=5.0)
        assert test_proc.exitcode == errno.ETIMEDOUT

    def test_maxread(self) -> None:
        """A maxread smaller than the motd still matches across reads."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        session.maxread = 1100
        session.expect(self.prompt1)
        assert session.before == self.motd
        session.send(self.enter)
        session.expect(self.prompt2)
        session.send(self.enter)
        session.expect(self.prompt3)
        session.send(self.exit)
        session.expect(pexpect.EOF)
        assert session.before == b""

    def test_fd_isalive(self) -> None:
        """The session stops being alive once the underlying socket is closed."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        assert session.isalive()
        sock.close()
        assert not session.isalive(), "Should not be alive after close()"

    def test_fd_isalive_poll(self) -> None:
        """isalive() tracks the closed socket when use_poll is set."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10, use_poll=True)
        assert session.isalive()
        sock.close()
        assert not session.isalive(), "Should not be alive after close()"

    def test_fd_isatty(self) -> None:
        """A socket is not a tty."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        assert not session.isatty()
        session.close()

    def test_fd_isatty_poll(self) -> None:
        """A socket is not a tty when use_poll is set either."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10, use_poll=True)
        assert not session.isatty()
        session.close()


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
