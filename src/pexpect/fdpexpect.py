"""Pexpect driven by a file descriptor you own.

Like :mod:`pexpect`, but it will work with any file descriptor that you pass
it. You are responsible for opening and closing the file descriptor. This
allows you to use Pexpect with sockets and named pipes (FIFOs).

.. note::
    socket.fileno() does not give a readable file descriptor on windows.
    Use :mod:`pexpect.socket_pexpect` for cross-platform socket support

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

import os
from typing import IO, TYPE_CHECKING, AnyStr, NoReturn, Protocol, cast, overload

from .exceptions import TIMEOUT, ExceptionPexpect
from .spawnbase import SpawnBase
from .utils import poll_ignore_interrupts, select_ignore_interrupts

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["fdspawn"]


class _HasFileno(Protocol):
    def fileno(self) -> int: ...


class fdspawn(SpawnBase[AnyStr]):
    """Like pexpect.spawn, but reading and writing a file descriptor you supply.

    For example, you could use it to read through a file looking for patterns,
    or to control a modem or serial device.
    """

    @overload
    def __init__(
        self: fdspawn[bytes],
        fd: int | _HasFileno,
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
        self: fdspawn[str],
        fd: int | _HasFileno,
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
        fd: int | _HasFileno,
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
        """Take a file descriptor (an int) or an object that supports ``fileno()``.

        All Python file-like objects support ``fileno()``.
        """
        if type(fd) is not int and hasattr(fd, "fileno"):
            fd = fd.fileno()

        if type(fd) is not int:
            msg = (
                "The fd argument is not an int. If this is a command string "
                "then maybe you want to use pexpect.spawn."
            )
            raise ExceptionPexpect(msg)

        try:  # make sure fd is a valid file descriptor
            os.fstat(fd)
        except OSError as err:
            msg = "The fd argument is not a valid file descriptor."
            raise ExceptionPexpect(msg) from err

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
        self.child_fd = fd
        self.own_fd = False
        self.closed = False
        self.name = f"<file descriptor {fd}>"
        self.use_poll = use_poll

    def close(self) -> None:
        """Close the file descriptor.

        Calling this method a second time does nothing, but if the file
        descriptor was closed elsewhere, :class:`OSError` will be raised.
        """
        if self.child_fd == -1:
            return

        self.flush()
        os.close(self.child_fd)
        self.child_fd = -1
        self.closed = True

    def isalive(self) -> bool:
        """Check whether the file descriptor is still valid.

        If :func:`os.fstat` does not raise an exception then we assume it is
        alive.
        """
        if self.child_fd == -1:
            return False
        try:
            os.fstat(self.child_fd)
        except OSError:
            return False
        return True

    def terminate(  # pragma: no cover
        self,
        # ARG002: override signature
        force: bool = False,  # unused; public positional flag  # noqa: ARG002
    ) -> NoReturn:
        """Raise an exception: terminating a file descriptor is not meaningful."""
        msg = "This method is not valid for file descriptors."
        raise ExceptionPexpect(msg)

    # These four methods are left around for backwards compatibility, but not
    # documented as part of fdpexpect. You're encouraged to use os.write
    # directly.
    def send(self, s: str | bytes) -> int:
        """Write to fd, return number of bytes written."""
        data = cast("AnyStr", self._coerce_send_string(s))
        self._log(data, "send")

        b = self._encoder.encode(data, final=False)
        return os.write(self.child_fd, b)

    def sendline(self, s: str | bytes) -> int:
        """Write to fd with trailing newline, return number of bytes written."""
        data = cast("AnyStr", self._coerce_send_string(s))
        return self.send(data + self.linesep)

    def write(self, s: str | bytes) -> None:
        """Write to fd, return None."""
        self.send(s)

    def writelines(self, sequence: Iterable[str | bytes]) -> None:
        """Call self.write() for each item in sequence."""
        for s in sequence:
            self.write(s)

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
        if os.name == "posix":  # pragma: no branch
            if timeout == -1:
                timeout = self.timeout
            rlist = [self.child_fd]
            wlist: list[int] = []
            xlist: list[int] = []
            if self.use_poll:
                rlist = poll_ignore_interrupts(rlist, timeout)
            else:
                rlist, wlist, xlist = select_ignore_interrupts(rlist, wlist, xlist, timeout)
            if self.child_fd not in rlist:
                msg = "Timeout exceeded."
                raise TIMEOUT(msg)
        # mypy checks this body once per string type but leaves the class's
        # type variable unexpanded in a super() call, so the base's AnyStr has
        # to be restated here.
        return cast("AnyStr", super().read_nonblocking(size))
