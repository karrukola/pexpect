"""Provides an interface like pexpect.spawn interface using subprocess.Popen."""

import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable
from queue import Empty, Queue
from typing import IO

from .exceptions import EOF
from .spawnbase import SpawnBase


class PopenSpawn(SpawnBase):
    """Talk to a child process started with :class:`subprocess.Popen`.

    Unlike :class:`pexpect.spawn` no pseudo-terminal is allocated, so this
    works on platforms without ptys at the cost of the child seeing a pipe
    rather than a terminal.
    """

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
            self.crlf = os.linesep.encode("ascii")
        else:
            self.crlf = self.string_type(os.linesep)

        kwargs = {
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

        self._read_queue = Queue()
        self._read_thread = threading.Thread(target=self._read_incoming)
        self._read_thread.daemon = True
        self._read_thread.start()

    _read_reached_eof = False

    def read_nonblocking(self, size: int, timeout: float | None) -> str | bytes:
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
        # Not elif: the branch above is exactly what leaves a None here, when
        # the spawn was built with timeout=None.
        if timeout is None:
            timeout = 1e6

        t0 = time.time()
        while (time.time() - t0) < timeout and size and len(buf) < size:
            try:
                incoming = self._read_queue.get_nowait()
            # PERF203: the except Empty IS the loop exit
            except Empty:  # an empty queue is how this loop terminates  # noqa: PERF203
                break
            else:
                if incoming is None:
                    self._read_reached_eof = True
                    break

                buf += self._decoder.decode(incoming, final=False)

        r, self._buf = buf[:size], buf[size:]

        self._log(r, "read")
        return r

    def _read_incoming(self) -> None:
        """Run in a thread to move output from a pipe to a queue."""
        fileno = self.proc.stdout.fileno()
        while 1:
            buf = b""
            try:
                buf = os.read(fileno, 1024)
            except OSError as e:
                # _log() hands its argument straight to the log streams, so an
                # exception object raises TypeError inside this thread, killing
                # it before it can queue the EOF sentinel below.
                message = str(e)
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
        s = self._coerce_send_string(s)
        self._log(s, "send")

        b = self._encoder.encode(s, final=False)
        return self.proc.stdin.write(b)

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
        self.proc.stdin.close()
