"""Provides an interface like pexpect.spawn interface using subprocess.Popen."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from queue import Empty, Queue
from typing import IO, TYPE_CHECKING, AnyStr, TypedDict, cast, overload

from .exceptions import EOF, TIMEOUT
from .spawnbase import SpawnBase

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


class _PopenKwargs(TypedDict, total=False):
    """The keyword arguments PopenSpawn hands to :class:`subprocess.Popen`.

    Collecting them in a mapping is what lets the Windows-only ones be added
    conditionally; stating their types here is what lets the call still pick
    the bytes flavour of Popen, which is the one this class reads from.
    """

    bufsize: int
    stdin: int
    stderr: int
    stdout: int
    cwd: str | None
    preexec_fn: Callable[[], None] | None
    env: dict[str, str] | None
    # STARTUPINFO only exists on Windows, where the block that sets this key
    # is the only one that reads it.
    startupinfo: object
    creationflags: int


class PopenSpawn(SpawnBase[AnyStr]):
    """Talk to a child process started with :class:`subprocess.Popen`.

    Unlike :class:`pexpect.spawn` no pseudo-terminal is allocated, so this
    works on platforms without ptys at the cost of the child seeing a pipe
    rather than a terminal.
    """

    # The child. Popen types both of its pipes as optional, because whether
    # they exist depends on its arguments, and this class always asks for both.
    # It reads them as bytes whatever this spawn's own encoding is: the decoding
    # to the caller's string type happens in read_nonblocking().
    proc: subprocess.Popen[bytes]

    # What the reader thread has handed over but read_nonblocking() has not
    # handed out yet, in the string type this spawn was created for.
    _buf: AnyStr

    @overload
    def __init__(
        self: PopenSpawn[bytes],
        cmd: str | list[str],
        timeout: float | None = 30,
        maxread: int = 2000,
        searchwindowsize: int | None = None,
        logfile: IO[bytes] | IO[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        encoding: None = None,
        codec_errors: str = "strict",
        preexec_fn: Callable[[], None] | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self: PopenSpawn[str],
        cmd: str | list[str],
        timeout: float | None = 30,
        maxread: int = 2000,
        searchwindowsize: int | None = None,
        logfile: IO[bytes] | IO[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        encoding: str = ...,
        codec_errors: str = "strict",
        preexec_fn: Callable[[], None] | None = None,
    ) -> None: ...

    def __init__(
        self,
        cmd: str | list[str],
        timeout: float | None = 30,
        maxread: int = 2000,
        searchwindowsize: int | None = None,
        logfile: IO[bytes] | IO[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        encoding: str | None = None,
        codec_errors: str = "strict",
        preexec_fn: Callable[[], None] | None = None,
    ) -> None:
        """Start *cmd* and pump its output into a queue from a reader thread."""
        super().__init__(
            timeout=timeout,
            maxread=maxread,
            searchwindowsize=searchwindowsize,
            logfile=logfile,
            encoding=encoding,
            codec_errors=codec_errors,
        )

        # Note that `SpawnBase` initializes `self.crlf` to `\r\n`
        # because the default behaviour for a PTY is to convert
        # incoming LF to `\r\n` (see the `onlcr` flag and
        # https://stackoverflow.com/a/35887657/5397009). Here we set
        # it to `os.linesep` because that is what the spawned
        # application outputs by default and `popen` doesn't translate
        # anything.
        if encoding is None:
            self.crlf = cast("AnyStr", os.linesep.encode("ascii"))
        else:
            self.crlf = cast("AnyStr", os.linesep)

        kwargs: _PopenKwargs = {
            "bufsize": 0,
            "stdin": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdout": subprocess.PIPE,
            "cwd": cwd,
            "preexec_fn": preexec_fn,
            "env": env,
        }

        if sys.platform == "win32":  # pragma: win32 cover
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        if isinstance(cmd, str) and sys.platform != "win32":
            cmd = shlex.split(cmd, posix=os.name == "posix")

        # S603: running the caller's cmd is the purpose
        self.proc = subprocess.Popen(cmd, **kwargs)  # running `cmd` is the point  # noqa: S603
        self.pid = self.proc.pid
        self.closed = False
        self._buf = self.string_type()

        # None is the sentinel the reader thread queues at the end of the output.
        self._read_queue: Queue[bytes | None] = Queue()
        self._read_thread = threading.Thread(target=self._read_incoming)
        self._read_thread.daemon = True
        self._read_thread.start()

    _read_reached_eof = False

    def read_nonblocking(self, size: int = 1, timeout: float | None = None) -> AnyStr:
        """Return up to *size* characters already read by the reader thread.

        Raises :exc:`EOF` once the queue is drained and the child's output
        pipe has closed.
        """
        buf = self._buf
        if self._read_reached_eof:
            # We have already finished reading. Use up any buffered data,
            # then raise EOF
            if buf:
                self._buf = buf[size:]
                return buf[:size]
            self.flag_eof = True
            msg = "End Of File (EOF)."
            raise EOF(msg)

        if timeout == -1:
            timeout = self.timeout
        if timeout is None:
            timeout = 1e6

        buf = self._fill_buffer(buf, size, timeout)

        r, self._buf = buf[:size], buf[size:]

        self._log(r, "read")
        return r

    def _fill_buffer(self, buf: AnyStr, size: int, timeout: float) -> AnyStr:
        """Grow *buf* with output the reader thread has queued, up to *size*.

        Waits for the first character rather than for all of *size* of them:
        once anything has arrived, whatever else is already queued is drained
        without waiting again, so a fast match costs about a millisecond
        rather than the full *timeout*. Raises :exc:`TIMEOUT` if the deadline
        passes with nothing read. If *size* is 0 the loop never runs, so this
        returns *buf* unchanged without waiting at all.
        """
        t0 = time.time()
        while size and len(buf) < size:
            if buf:
                try:
                    incoming = self._read_queue.get_nowait()
                except Empty:
                    break
            else:
                remaining = timeout - (time.time() - t0)
                if remaining <= 0:
                    msg = "Timeout exceeded."
                    raise TIMEOUT(msg)
                try:
                    incoming = self._read_queue.get(timeout=remaining)
                except Empty:
                    msg = "Timeout exceeded."
                    raise TIMEOUT(msg) from None

            if incoming is None:
                self._read_reached_eof = True
                break

            buf += self._decoder.decode(incoming, final=False)

        return buf

    def _read_incoming(self) -> None:
        """Run in a thread to move output from a pipe to a queue."""
        fileno = cast("IO[bytes]", self.proc.stdout).fileno()
        while 1:
            buf = b""
            try:
                buf = os.read(fileno, 1024)
            except OSError as err:
                # The log takes the string type this spawn was created for, so
                # the error is reported in that type rather than as the object.
                message = str(err)
                self._log(message.encode("utf-8") if self.encoding is None else message, "read")

            if not buf:
                # This indicates we have reached EOF
                self._read_queue.put(None)
                return

            self._read_queue.put(buf)

    def write(self, s: str | bytes) -> None:
        """Send data to the subprocess' stdin, like send() but returning nothing."""
        self.send(s)

    def writelines(self, sequence: Iterable[str | bytes]) -> None:
        """Call send() for each element in the sequence.

        The sequence can be any iterable object producing strings, typically a
        list of strings. This does not add line separators. There is no return
        value.
        """
        for s in sequence:
            self.send(s)

    def send(self, s: str | bytes) -> int:
        """Send data to the subprocess' stdin.

        Returns the number of bytes written.
        """
        data = cast("AnyStr", self._coerce_send_string(s))
        self._log(data, "send")

        b = self._encoder.encode(data, final=False)
        return cast("IO[bytes]", self.proc.stdin).write(b)

    def sendline(self, s: str | bytes = "") -> int:
        """Send string ``s`` to the child, with os.linesep appended.

        Returns the number of bytes written.
        """
        n = self.send(s)
        return n + self.send(self.linesep)

    def wait(self) -> int:
        """Wait for the subprocess to finish.

        Returns the exit code.
        """
        status = self.proc.wait()
        if status >= 0:
            self.exitstatus = status
            self.signalstatus = None
        else:
            self.exitstatus = None
            self.signalstatus = -status
        self.terminated = True
        return status

    def kill(self, sig: int) -> None:
        """Send a Unix signal to the subprocess.

        Use constants from the :mod:`signal` module to specify which signal.
        """
        if sys.platform == "win32":  # pragma: win32 cover
            if sig in [signal.SIGINT, signal.CTRL_C_EVENT]:
                sig = signal.CTRL_C_EVENT
            elif sig in [signal.SIGBREAK, signal.CTRL_BREAK_EVENT]:
                sig = signal.CTRL_BREAK_EVENT
            else:
                sig = signal.SIGTERM

        os.kill(self.proc.pid, sig)

    def sendeof(self) -> None:
        """Close the stdin pipe from the writing end."""
        cast("IO[bytes]", self.proc.stdin).close()

    def isalive(self) -> bool:
        """Test whether the child process is still running.

        This is non-blocking. If the child has already exited, this records
        its exitstatus or signalstatus and sets terminated -- the way
        :meth:`wait` does -- rather than merely reporting that it is gone.
        """
        if self.proc.poll() is None:
            return True
        self.wait()
        return False

    def close(self) -> None:
        """Close the connection with the child application.

        Calling this method a second time does nothing. There is no
        pseudo-terminal here for stdin EOF to reliably end the child: a
        child that ignores it (``sleep 5``) would otherwise make ``with``
        block for five seconds, and one that never exits on stdin EOF would
        block forever. So, like :meth:`pty_spawn.spawn.close`, this
        escalates instead of only waiting: close stdin, wait, SIGTERM, wait,
        SIGKILL, wait.
        """
        if self.closed:
            return

        self._close_async_transport()
        self.flush()
        cast("IO[bytes]", self.proc.stdin).close()

        try:
            self.proc.wait(timeout=self.delayafterclose)
        except subprocess.TimeoutExpired:
            self.kill(signal.SIGTERM)
            try:
                self.proc.wait(timeout=self.delayafterterminate)
            except subprocess.TimeoutExpired:
                self.kill(signal.SIGKILL)
                self.proc.wait()

        self.isalive()  # record exitstatus/signalstatus/terminated

        # The child is gone, so the write end of its output pipe is closed and
        # the reader thread is about to see the end of it and stop. Waiting for
        # that before closing the read end is what keeps the descriptor out of
        # the thread's hands: it reads by descriptor number, and a number
        # closed under a blocked read is one the kernel may hand to something
        # else. The wait is bounded rather than open-ended because a grandchild
        # can hold the write end open past the child's death, and close() must
        # not block on one.
        self._read_thread.join(timeout=self.delayafterclose)
        cast("IO[bytes]", self.proc.stdout).close()
        self.closed = True
