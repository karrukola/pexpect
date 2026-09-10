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

import sys
import unittest
from typing import TYPE_CHECKING

import pytest

import pexpect
from pexpect import fdpexpect

from . import test_socket

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable

pytestmark = [
    pytest.mark.usefixtures("fast_sleep"),
    pytest.mark.skipif(
        sys.platform == "win32",
        # The server is a bound method of the test case, which no spawn start
        # method can carry, so it needs a forked subprocess.
        reason="needs os.fork to run its socket server",
    ),
]


class ExpectTestCase(test_socket.ExpectTestCase):
    """Run the test_socket suite through fdpexpect instead of socket_pexpect."""

    def spawn(
        self, sock: socket.socket, timeout: float = 30, *, use_poll: bool = False
    ) -> fdpexpect.fdspawn[bytes]:
        """Spawn on the socket's file descriptor rather than on the socket itself."""
        return fdpexpect.fdspawn(sock.fileno(), timeout=timeout, use_poll=use_poll)

    def test_not_int(self) -> None:
        """A non-integer file descriptor is rejected."""
        # What is under test is the argument the signature already rules out, so
        # the constructor is reached through a name that accepts anything.
        fdspawn: Callable[..., fdpexpect.fdspawn[bytes]] = fdpexpect.fdspawn
        with pytest.raises(pexpect.ExceptionPexpect):
            fdspawn("bogus", timeout=10)

    def test_not_file_descriptor(self) -> None:
        """An invalid file descriptor number is rejected."""
        with pytest.raises(pexpect.ExceptionPexpect):
            fdpexpect.fdspawn(-1, timeout=10)

    def test_fileobj(self) -> None:
        """Accept an object with a fileno(), and tolerate a second close()."""
        sock = self.connect()
        session = fdpexpect.fdspawn(sock, timeout=10)  # Should get the fileno from the socket
        session.expect(self.prompt1)
        session.close()
        assert not session.isalive()
        session.close()  # Smoketest - should be able to call this again


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
