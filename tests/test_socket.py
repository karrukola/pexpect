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

from __future__ import annotations

import contextlib
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
from pexpect import fdpexpect, socket_pexpect

from . import pexpect_test_case

pytestmark = [
    pytest.mark.usefixtures("fast_sleep"),
    pytest.mark.skipif(
        sys.platform == "win32",
        # The server is a bound method of the test case, which no spawn start
        # method can carry, so it needs a forked subprocess.
        reason="needs os.fork to run its socket server",
    ),
]

if TYPE_CHECKING:
    from multiprocessing.context import DefaultContext, ForkContext
    from multiprocessing.synchronize import Event

    # get_context() hands back a different class per start method, and only
    # those concrete classes carry Process; their shared base does not.
    MpContext = DefaultContext | ForkContext

    # What spawn() hands back: this suite is run a second time by
    # tests/test_socket_fd.py, which spawns on the socket's file descriptor.
    SocketSession = socket_pexpect.SocketSpawn[bytes] | fdpexpect.fdspawn[bytes]

# Python 3.14 changed the non-macOS POSIX default to forkserver
# but the code in this module does not work with it
# See https://github.com/python/cpython/issues/125714
mp_context: MpContext
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
        if not self._family_works(socket.AF_INET) and self._family_works(socket.AF_INET6):
            self.af = socket.AF_INET6
            self.host = "::1"
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

    @staticmethod
    def _family_works(family: socket.AddressFamily) -> bool:
        """Report whether a stream socket of *family* can be created here.

        The socket is closed again straight away: this asks the kernel a
        question about the machine, and a socket left over from asking it is
        reported as an unclosed one by whichever later test collects it.
        """
        try:
            with socket.socket(family, socket.SOCK_STREAM):
                return True
        except OSError:
            return False

    @staticmethod
    def _close_connection(sock: socket.socket) -> None:
        """Close *sock* unless its descriptor has already been closed for it.

        A session spawned on a socket owns the descriptor from then on.
        :meth:`SocketSpawn.close` closes the socket object, which leaves this
        a second, harmless call; but tests/test_socket_fd.py spawns on the
        bare descriptor, and :meth:`fdspawn.close` closes that, leaving the
        socket object holding a number that is no longer its own. Closing it
        again is EBADF, and leaving it unclosed is a ResourceWarning.
        """
        with contextlib.suppress(OSError):
            sock.close()

    def connect(self) -> socket.socket:
        """Return a socket connected to the test server, closed when the test ends."""
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        self.addCleanup(self._close_connection, sock)
        sock.connect((self.host, self.port))
        return sock

    def tearDown(self) -> None:
        """Interrupt the socket server subprocess and reap it."""
        pid = self.server_process.pid
        assert pid is not None
        os.kill(pid, signal.SIGINT)
        self.server_process.join(timeout=5.0)
        if self.server_process.is_alive():
            # Every test in this class and in tests/test_socket_fd.py listens on
            # the one port, so a server that ignored the interrupt would hold it
            # against whichever test the shuffle runs next -- as a daemon, past
            # this process too. SIGKILL cannot be ignored; the join that follows
            # is what makes the port free before the next setUp binds it.
            self.server_process.kill()
            self.server_process.join(timeout=5.0)
        pexpect_test_case.PexpectTestCase.tearDown(self)

    def socket_server(self, server_up: Event) -> None:
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
    ) -> SocketSession:
        """Override me with other ways of spawning on a socket."""
        return socket_pexpect.SocketSpawn(sock, timeout=timeout, use_poll=use_poll)

    def socket_fn(self, timed_out: Event, all_read: Event) -> None:
        """Read everything the server sent, then time out on a second read.

        Runs in a subprocess and exits with ETIMEDOUT once the timeout is seen.
        """
        result = 0
        try:
            sock = socket.socket(self.af, socket.SOCK_STREAM)
            sock.connect((self.host, self.port))
            session = self.spawn(sock, timeout=_READ_TIMEOUT)
            # The server writes the motd and the first prompt as two separate
            # sends, so one read is not guaranteed to see both: a read that
            # lands between them returns the motd alone and leaves the prompt
            # queued, where it satisfies the read below that has to time out.
            # This process would then exit 0 without ever setting `timed_out`,
            # and the caller -- which waits on that event with no deadline of
            # its own -- would spin until the suite's per-test budget killed it.
            # Read until the whole greeting is in.
            greeting = self.motd + self.prompt1
            seen = b""
            while len(seen) < len(greeting):
                seen += session.read_nonblocking(size=4096)
            all_read.set()
            # This read should timeout
            session.read_nonblocking(size=4096)
        except pexpect.TIMEOUT:
            timed_out.set()
            result = errno.ETIMEDOUT
        sys.exit(result)

    def test_socket(self) -> None:
        """Walk the whole prompt sequence with send() and end at EOF."""
        sock = self.connect()
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
        sock = self.connect()
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
        sock = self.connect()
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
        pid = test_proc.pid
        assert pid is not None
        os.kill(pid, signal.SIGWINCH)
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
        pid = test_proc.pid
        assert pid is not None
        while not timed_out.is_set():
            os.kill(pid, signal.SIGWINCH)
            # Event.wait paces the signals with real time and returns as soon as
            # the child reports the timeout it was interrupted out of.
            timed_out.wait(timeout=0.001)
        test_proc.join(timeout=5.0)
        assert test_proc.exitcode == errno.ETIMEDOUT

    def test_maxread(self) -> None:
        """A maxread smaller than the motd still matches across reads."""
        sock = self.connect()
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
        sock = self.connect()
        session = self.spawn(sock, timeout=10)
        assert session.isalive()
        sock.close()
        assert not session.isalive(), "Should not be alive after close()"

    def test_fd_isalive_poll(self) -> None:
        """isalive() tracks the closed socket when use_poll is set."""
        sock = self.connect()
        session = self.spawn(sock, timeout=10, use_poll=True)
        assert session.isalive()
        sock.close()
        assert not session.isalive(), "Should not be alive after close()"

    def test_fd_isatty(self) -> None:
        """A socket is not a tty."""
        sock = self.connect()
        session = self.spawn(sock, timeout=10)
        assert not session.isatty()
        session.close()

    def test_fd_isatty_poll(self) -> None:
        """A socket is not a tty when use_poll is set either."""
        sock = self.connect()
        session = self.spawn(sock, timeout=10, use_poll=True)
        assert not session.isatty()
        session.close()


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
