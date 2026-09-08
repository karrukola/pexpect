"""Pexpect driven by a socket you own.

Like :mod:`pexpect`, but it will work with any socket that you pass it. You
are responsible for opening and closing the socket.

PEXPECT LICENSE

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

import socket
from contextlib import contextmanager
from typing import IO, TYPE_CHECKING, AnyStr, cast, overload

from .exceptions import EOF, TIMEOUT
from .spawnbase import SpawnBase

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

__all__ = ["SocketSpawn"]


class SocketSpawn(SpawnBase[AnyStr]):
    """Like :mod:`pexpect.fdpexpect`, but over the cross-platform socket api.

    Using the python socket api rather than the unix-specific file descriptor
    api means this works with remote connections on both unix and windows.
    """

    @overload
    def __init__(
        self: SocketSpawn[bytes],
        socket: socket.socket,
        args: None = None,
        timeout: float | None = 30,
        maxread: int = 2000,
        searchwindowsize: int | None = None,
        logfile: IO[bytes] | IO[str] | None = None,
        encoding: None = None,
        codec_errors: str = "strict",
        use_poll: bool = False,
    ) -> None: ...

    @overload
    def __init__(
        self: SocketSpawn[str],
        socket: socket.socket,
        args: None = None,
        timeout: float | None = 30,
        maxread: int = 2000,
        searchwindowsize: int | None = None,
        logfile: IO[bytes] | IO[str] | None = None,
        encoding: str = ...,
        codec_errors: str = "strict",
        use_poll: bool = False,
    ) -> None: ...

    def __init__(
        self,
        socket: socket.socket,
        # ARG002: signature parity with spawn
        args: None = None,  # accepted for signature parity with `spawn`  # noqa: ARG002
        timeout: float | None = 30,
        maxread: int = 2000,
        searchwindowsize: int | None = None,
        logfile: IO[bytes] | IO[str] | None = None,
        encoding: str | None = None,
        codec_errors: str = "strict",
        use_poll: bool = False,  # positional flag is public API
    ) -> None:
        """Take an open socket."""
        self.args = None
        self.command = None
        SpawnBase.__init__(
            self,
            timeout,
            maxread,
            searchwindowsize,
            logfile,
            encoding=encoding,
            codec_errors=codec_errors,
        )
        self.socket = socket
        self.child_fd = socket.fileno()
        self.closed = False
        self.name = f"<socket {socket}>"
        self.use_poll = use_poll

    def close(self) -> None:
        """Close the socket.

        Calling this method a second time does nothing, but if the file
        descriptor was closed elsewhere, :class:`OSError` will be raised.
        """
        if self.child_fd == -1:
            return

        self._close_async_transport()
        self.flush()
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()
        self.child_fd = -1
        self.closed = True

    def isalive(self) -> bool:
        """Alive if the fileno is valid."""
        return self.socket.fileno() >= 0

    def send(self, s: str | bytes) -> int:
        """Write to socket, return number of bytes written."""
        data = cast("AnyStr", self._coerce_send_string(s))
        self._log(data, "send")

        b = self._encoder.encode(data, final=False)
        self.socket.sendall(b)
        return len(b)

    def sendline(self, s: str | bytes) -> int:
        """Write to socket with trailing newline, return number of bytes written."""
        data = cast("AnyStr", self._coerce_send_string(s))
        return self.send(data + self.linesep)

    def write(self, s: str | bytes) -> None:
        """Write to socket, return None."""
        self.send(s)

    def writelines(self, sequence: Iterable[str | bytes]) -> None:
        """Call self.write() for each item in sequence."""
        for s in sequence:
            self.write(s)

    @contextmanager
    def _timeout(self, timeout: float | None) -> Iterator[None]:
        saved_timeout = self.socket.gettimeout()
        try:
            self.socket.settimeout(timeout)
            yield
        finally:
            self.socket.settimeout(saved_timeout)

    def read_nonblocking(self, size: int = 1, timeout: float | None = -1) -> AnyStr:
        """Read from the file descriptor and return the result as a string.

        The read_nonblocking method of :class:`SpawnBase` assumes that a call
        to os.read will not block (timeout parameter is ignored). This is not
        the case for POSIX file-like objects such as sockets and serial ports.

        Use :func:`select.select`, timeout is implemented conditionally for
        POSIX systems.

        :param int size: Read at most *size* bytes.
        :param int timeout: Wait timeout seconds for file descriptor to be
            ready to read. When -1 (default), use self.timeout. When 0, poll.
        :return: String containing the bytes read
        """
        if timeout == -1:
            timeout = self.timeout
        try:
            with self._timeout(timeout):
                s = self.socket.recv(size)
                if s == b"":
                    self.flag_eof = True
                    msg = "Socket closed"
                    raise EOF(msg)
                decoded = self._decoder.decode(s, final=False)
                self._log(decoded, "read")
                return decoded
        except (TimeoutError, BlockingIOError) as err:
            msg = "Timeout exceeded."
            raise TIMEOUT(msg) from err
