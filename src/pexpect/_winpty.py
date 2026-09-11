"""The Windows process backend: pexpect's pty surface over pywinpty's ConPTY.

pywinpty ships winpty.PtyProcess, shaped deliberately like ptyprocess's class
of the same name, and it is used here for everything to do with the console:
starting the child, resizing it, terminating it, reaping it. It also gives a
working fileno(), which was not a given -- a reader thread pumps the ConPTY
output into a loopback socket, and select() accepts socket descriptors on
Windows -- so pexpect's readiness path needs nothing special.

Its read() is not used. That method returns str while pexpect is bytes end to
end and decodes with the caller's own encoding and codec_errors; and it re-reads
one byte at a time until its buffer decodes as UTF-8, which is right for
truncated UTF-8 and never terminates on invalid UTF-8 -- a child emitting cp1252
or raw binary blocks it inside a loop no pexpect timeout reaches. Reading the
socket it already exposes avoids that hang, but does not recover byte
exactness: the reader thread decodes the native read as UTF-8 and re-encodes
it before writing to the socket, so non-UTF-8 child output is already mangled
by the time it gets there. What read_bytes() returns is the bytes pywinpty's
reader produced, not the child's own bytes -- the guarantee pexpect's bytes
mode gives on POSIX, that read() returns exactly what the child wrote, does
not hold here.

That reader thread also writes the literal sentinel b'0011Ignore' into the
socket for every empty native read, and strips it back out only inside the
read() method above, which this module does not call. read_bytes() strips it
instead, and does so through a buffer of its own rather than on the chunk the
caller's size happened to ask for: recognising ten bytes is impossible in a
one-byte recv(), and read_nonblocking(size=1) -- that parameter's default, and
what pxssh's login loop uses -- would otherwise hand the sentinel's first
byte to the caller as child output. Stripping by search rather than by
equality is for the same reason from the other side: the kernel can coalesce a
sentinel-only send with the next real one. A child that prints that exact
string still loses it; that defect is inherited from pywinpty, not introduced
here.

Two more properties of the dependency are inherited rather than fixed,
recorded here so they are not rediscovered as pexpect bugs:

* Each spawn opens a listening socket on 127.0.0.1, which a local process
  could race the connect on to read another user's child output.
* The reader thread writes to that socket with socket.send() rather than
  sendall() (winpty/ptyprocess.py:355), so a partial send silently drops the
  remainder of a chunk.
"""

from __future__ import annotations

import os
import select
import signal
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import winpty

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

# The reader thread in winpty/ptyprocess.py writes this into the socket for
# every empty native read, and only winpty.PtyProcess.read() strips it back
# out -- see the module docstring for why read_bytes() does not call that.
_EMPTY_READ_SENTINEL = b"0011Ignore"

# How many bytes read_bytes() asks the socket for, however few the caller
# wanted. recv() returns as soon as anything at all is available, so asking
# for more than `size` costs no additional blocking, and asking for at least
# the sentinel's length is what makes stripping it possible at all.
_MIN_RECV = 1024


class PtyProcessError(Exception):
    """Raised for a backend failure, and for a call Windows cannot honour.

    pty_spawn turns this into ExceptionPexpect through _wrap_ptyprocess_err,
    which is how an unsupported call reaches the caller as the one exception
    type pexpect raises.
    """


@contextmanager
def _as_ptyproc_err() -> Iterator[None]:
    """Re-raise whatever pywinpty throws as PtyProcessError.

    winpty.WinptyError derives from Exception rather than from OSError, and
    winpty.PtyProcess.write() raises a bare EOFError once the child has gone,
    so neither is caught by anything pexpect has. This wraps every call into
    the dependency, which is what makes PtyProcessError's docstring above true
    rather than aspirational: pty_spawn's own _wrap_ptyprocess_err() catches
    that type and nothing else.
    """
    try:
        yield
    except (winpty.WinptyError, EOFError, OSError) as e:
        raise PtyProcessError(*e.args) from e


class PtyProcess:
    """A child running in a ConPTY, presented as pexpect's pty backend."""

    def __init__(self, proc: winpty.PtyProcess) -> None:
        self._proc = proc
        # pywinpty's own PtyProcess copies this straight from winpty.PTY.pid,
        # which its stub declares Optional[int], so mypy resolves it as
        # int | None wherever the package is really installed -- the Windows
        # runner. A spawn() that returned rather than raising has a running
        # child and so a pid, and pty_spawn copies this to spawn.pid, where
        # int is the documented type; the cast is that reasoning, written down.
        self.pid: int = cast("int", proc.pid)
        self.fd: int = proc.fd
        # What read_bytes() has read from the socket and not yet handed over.
        # See its docstring: the sentinel is ten bytes and the caller's size
        # may be one, so reading ahead is not an optimisation but the only way
        # to recognise it. _peer_closed is the socket's FIN, kept apart from
        # flag_eof because that one is pexpect's answer to eof() and must not
        # become True while buffered output is still undelivered.
        self._buffer = bytearray()
        self._peer_closed = False
        self.flag_eof = False
        self.terminated = False
        self.status: int | None = None
        self.exitstatus: int | None = None
        # A Windows process never exits by signal, so this is None for the
        # life of the object. pexpect copies it to spawn.signalstatus.
        self.signalstatus: int | None = None
        self.delayafterterminate = 0.1

    @classmethod
    def spawn(
        cls,
        argv: Sequence[str | bytes],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        echo: bool = True,
        preexec_fn: Callable[[], None] | None = None,
        dimensions: tuple[int, int] = (24, 80),
    ) -> PtyProcess:
        """Start *argv* in a ConPTY and return the backend wrapping it.

        The signature is ptyprocess's, because pty_spawn._ptyproc_kwargs() calls
        it with those names. `echo=False` and `preexec_fn` are refused: ConPTY
        keeps echo in the child's own console host, out of the parent's reach,
        and there is no fork for a preexec hook to run between.
        """
        if not echo:
            msg = "echo=False is not supported on Windows: ConPTY echo belongs to the child"
            raise PtyProcessError(msg)
        if preexec_fn is not None:
            msg = "preexec_fn is not supported on Windows: there is no fork to run it between"
            raise PtyProcessError(msg)
        # pty_spawn re-encodes the argument list when an encoding is in force,
        # and pywinpty resolves argv[0] with shutil.which() and joins the rest
        # with subprocess.list2cmdline(), both of which want str.
        decoded = [a if isinstance(a, str) else os.fsdecode(a) for a in argv]
        with _as_ptyproc_err():
            proc = winpty.PtyProcess.spawn(decoded, cwd=cwd, env=env, dimensions=dimensions)
        return cls(proc)

    def _pending_count(self) -> int:
        """How many buffered bytes read_bytes() would hand over right now.

        Everything in the buffer except a tail that is still a proper prefix
        of the sentinel. Those bytes are withheld because the reader thread's
        ten can arrive split across two recv() calls, and half a sentinel
        delivered is half a sentinel in the caller's expect() buffer for good.
        Once the socket has closed nothing can arrive to complete such a tail,
        so it was the child's own output after all and is handed over.
        """
        if self._peer_closed:
            return len(self._buffer)
        held = min(len(self._buffer), len(_EMPTY_READ_SENTINEL) - 1)
        while held and self._buffer[-held:] != _EMPTY_READ_SENTINEL[:held]:
            held -= 1
        return len(self._buffer) - held

    def _socket_readable(self) -> bool:
        """Whether the socket has anything more to give right now.

        select() with a zero timeout, which is the portable check: the
        descriptor is a WinSock socket, which is what Windows select()
        accepts, and pty_spawn._ready() already selects on this same one.
        MSG_PEEK and a non-blocking socket were both considered and rejected
        -- the first is another way to ask the same question, and the second
        would change what every other read on this socket does.

        It answers one question only: can a withheld sentinel prefix still be
        completed? If nothing is arriving, it cannot, and blocking in recv()
        to find out would hang a read that has bytes to hand over. At a real
        end of file the FIN makes the socket readable, so a genuinely split
        sentinel is still completed rather than truncated.
        """
        with _as_ptyproc_err():
            readable, _, _ = select.select([self._proc.fileobj], [], [], 0)
        return bool(readable)

    def pending(self) -> bool:
        """Whether output is buffered here that select() on the fd cannot see.

        pty_spawn's readiness check asks, because read_bytes() reads the
        socket in chunks larger than the caller asked for: without this, a
        read_nonblocking(size=1) would take one byte of a 1024-byte chunk and
        then time out waiting for a socket that has already been drained.

        A buffer that is entirely a withheld sentinel prefix counts too, once
        the socket has gone quiet: read_bytes() hands those bytes over rather
        than blocking for a sentinel that is not coming, so readiness has to
        say so or pty_spawn would wait out its whole timeout for output it is
        already holding.
        """
        if self._pending_count() > 0:
            return True
        return bool(self._buffer) and not self._socket_readable()

    def read_bytes(self, size: int) -> bytes:
        """Read at most *size* bytes of the child's output.

        Reads the socket pywinpty's reader thread feeds, through the buffer
        the sentinel forces on us: recv() is asked for _MIN_RECV bytes or
        *size*, whichever is larger, the sentinel is stripped from the
        accumulated buffer, and up to *size* bytes come back from the front
        of it. What that leaves buffered is what pending() exists to report.

        A genuinely empty read -- the socket has closed -- is end of file,
        which is what SpawnBase.read_nonblocking's BSD-style arm turns into
        pexpect's EOF. It is reported only once every buffered byte has been
        handed over, so no output is lost to it. A read that is empty only
        once the sentinel is stripped out is not end of file: it is retried.

        Nor does the retry spin under the configuration this module assumes.
        PYWINPTY_BLOCK defaults to 1, which makes the native read block, so a
        falsy native read -- the only thing that produces a sentinel -- should
        be uncommon while the child has something to say. What happens at the
        end of file is not established by anything readable from here: their
        pty.read() is native code, and whether a blocking read returns the
        empty string or raises once the child has gone is in neither the stub,
        their Python source nor their tests. If it returns empty, the sentinel
        arrives immediately before the FIN; if it raises, their reader thread
        breaks out at winpty/ptyprocess.py:368 and sends nothing at all.
        Either way this loop terminates, and neither way is assumed.

        Setting PYWINPTY_BLOCK=0 makes the reader thread poll and emit the
        sentinel roughly once a millisecond, which would spin this loop for as
        long as the child keeps running with nothing to say; this module
        neither sets nor recommends that.
        """
        while True:
            ready = self._pending_count()
            if not ready and self._buffer and not self._socket_readable():
                # The whole buffer is a withheld sentinel prefix and nothing
                # is arriving behind it to say whether it is one. Looping for
                # more data here is a blocking recv() on an empty socket --
                # an unbounded hang, inside the one library whose reason for
                # existing is that reads have timeouts. A child that echoes
                # a caller's "0" back and then waits for input is enough to
                # reach it, and ConPTY echo is always on. So the bytes are
                # the child's after all, on the same reasoning as end of
                # file: what cannot be completed was never a sentinel.
                ready = len(self._buffer)
            if ready:
                chunk = bytes(self._buffer[: min(size, ready)])
                del self._buffer[: len(chunk)]
                return chunk
            if self._peer_closed:
                self.flag_eof = True
                return b""
            with _as_ptyproc_err():
                try:
                    data: bytes = self._proc.fileobj.recv(max(size, _MIN_RECV))
                except (ConnectionResetError, ConnectionAbortedError):
                    # An abortive close of the loopback socket is one of the
                    # ways a child exit can present on Windows, and it means
                    # the same thing as the orderly FIN below: there is no
                    # more output. Reporting it as an error instead would
                    # turn an ordinary end of file into an exception out of
                    # expect().
                    data = b""
            if data:
                self._buffer += data
                # A sentinel-only chunk, and one the kernel has coalesced with
                # the next real chunk, both come through here -- a plain
                # equality check would miss the second case.
                self._buffer[:] = self._buffer.replace(_EMPTY_READ_SENTINEL, b"")
            else:
                self._peer_closed = True

    def write_bytes(self, data: bytes) -> int:
        """Write *data* to the child and return the number of bytes taken.

        winpty.PTY.write() takes a Rust str, by way of PyUnicode_AsUTF8AndSize
        with surrogatepass, so a lone surrogate -- what surrogateescape would
        produce for a non-UTF-8 byte -- is not carried through unchanged: it
        is either rejected outright or re-encoded into three-byte WTF-8. A
        non-UTF-8 payload is refused up front instead, rather than risking a
        bare UnicodeEncodeError or silent corruption. On success the byte
        count pexpect's send() contract wants is len(data) itself, since valid
        UTF-8 decodes to exactly that many bytes; pywinpty's own return value
        is used only to tell a short write from a complete one, for which see
        the comment on the comparison below.
        """
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            msg = f"write_bytes() cannot send non-UTF-8 bytes on Windows: {e}"
            raise PtyProcessError(msg) from e
        # winpty.PtyProcess.write() raises a bare EOFError if the child has
        # already exited; PtyProcessError is what lets terminate() and
        # pty_spawn's _wrap_ptyprocess_err tell that from a real bug.
        with _as_ptyproc_err():
            written = self._proc.write(text)
        if written < len(text):
            # Compared against the character count, not len(data), because
            # pywinpty declares PTY.write() as returning an int and documents
            # no unit for it: the native side could be counting UTF-8 bytes,
            # UTF-16 code units, or UTF-16 bytes, and its own test suite calls
            # the value `num_bytes` without asserting anything about it. Every
            # one of those encodings spends at least one unit per character,
            # so fewer units than characters is a short write under all of
            # them, while an equality check against len(data) would raise on
            # every non-ASCII send if the unit is not the one assumed.
            msg = (
                f"write_bytes() reported {written} units written for "
                f"{len(text)} characters, which is a short write"
            )
            raise PtyProcessError(msg)
        return len(data)

    def isatty(self) -> bool:
        """Return whether this end of the ConPTY is still open.

        Which is what POSIX's os.isatty(fd) answers: a spawned child is on a
        console until close() takes the descriptor away. pywinpty's own
        isatty() returns isalive() instead, so it goes False while the
        console is still there to be read -- this does not follow it.
        """
        return not self.closed

    @property
    def closed(self) -> bool:
        """Whether close() has run."""
        return self.fd == -1

    def fileno(self) -> int:
        """Return the descriptor pexpect selects on."""
        return self.fd

    def getecho(self) -> bool:
        """Refuse: ConPTY echo is a property of the child's console host."""
        msg = "getecho() is not supported on Windows"
        raise PtyProcessError(msg)

    # ARG002: state is part of the ptyprocess signature pty_spawn calls into;
    # unused because the call is refused outright.
    def setecho(self, state: bool) -> None:  # noqa: ARG002
        """Refuse: ConPTY echo is a property of the child's console host."""
        msg = "setecho() is not supported on Windows"
        raise PtyProcessError(msg)

    def sendcontrol(self, char: str) -> tuple[int, bytes]:
        """Send one control character by mnemonic name.

        Returns the pair pty_spawn unpacks: bytes written, and the byte sent,
        which pexpect logs itself.
        """
        char = char.lower()
        code = ord(char)
        if ord("a") <= code <= ord("z"):
            byte = bytes([code - ord("a") + 1])
        else:
            mnemonics = {
                "@": 0,
                "`": 0,
                "[": 27,
                "{": 27,
                "\\": 28,
                "|": 28,
                "]": 29,
                "}": 29,
                "^": 30,
                "~": 30,
                "_": 31,
                "?": 127,
            }
            if char not in mnemonics:
                return 0, b""
            byte = bytes([mnemonics[char]])
        return self.write_bytes(byte), byte

    def sendeof(self) -> tuple[int, bytes]:
        """Send end of file, which on a Windows console is Ctrl-Z."""
        byte = b"\x1a"
        return self.write_bytes(byte), byte

    def sendintr(self) -> tuple[int, bytes]:
        """Send Ctrl-C, which ConPTY turns into a console interrupt."""
        byte = b"\x03"
        return self.write_bytes(byte), byte

    def getwinsize(self) -> tuple[int, int]:
        """Return the console size as (rows, cols).

        pywinpty answers from the value it cached the last time it was told
        (winpty/ptyprocess.py:334), not from the console, so a resize the
        child performed for itself is not reflected here. The POSIX backend
        reads the real ioctl and would show it.
        """
        with _as_ptyproc_err():
            rows, cols = self._proc.getwinsize()
        return rows, cols

    def setwinsize(self, rows: int, cols: int) -> None:
        """Resize the ConPTY."""
        with _as_ptyproc_err():
            self._proc.setwinsize(rows, cols)

    def isalive(self) -> bool:
        """Whether the child is still running, reaping it if it is not."""
        with _as_ptyproc_err():
            alive = self._proc.isalive()
        if alive:
            return True
        self._reap()
        return False

    def wait(self) -> int | None:
        """Block until the child exits and return its exit status."""
        with _as_ptyproc_err():
            self._proc.wait()
        self._reap()
        return self.exitstatus

    def _reap(self) -> None:
        """Record the exit status once, the way ptyprocess's isalive() does."""
        if not self.terminated:
            with _as_ptyproc_err():
                self.exitstatus = self._proc.exitstatus
            # ptyprocess's `status` is the raw os.waitpid() status, which has no
            # Windows counterpart. With signalstatus always None, the exit code
            # is the whole of what there is to report.
            self.status = self.exitstatus
            self.terminated = True

    def terminate(self, force: bool = False) -> bool:
        """Stop the child, returning whether it is gone.

        Ctrl-C first, which a console application can handle; then, only with
        *force*, TerminateProcess, which it cannot. There is no middle rung:
        the POSIX ladder's SIGHUP and SIGCONT have no Windows counterpart.
        """
        if not self.isalive():
            return True
        try:
            self.sendintr()
        except PtyProcessError:
            # write_bytes() raises this if the child exited between the
            # isalive() check above and the write landing -- gone is the
            # answer terminate() is asked for, not a failure to report.
            return not self.isalive()
        time.sleep(self.delayafterterminate)
        if not self.isalive():
            return True
        if force:
            self.kill(signal.SIGTERM)
            time.sleep(self.delayafterterminate)
            return not self.isalive()
        return False

    def kill(self, sig: int) -> None:
        """Send *sig* to the child, for the two signals this accepts.

        os.kill() on Windows recognises exactly two values, CTRL_C_EVENT and
        CTRL_BREAK_EVENT, which it delivers through GenerateConsoleCtrlEvent,
        and treats every other value as a TerminateProcess exit code -- so a
        SIGHUP here would terminate the child rather than hang it up, which is
        why anything not named below is refused.

        Those two are refused as well, and SIGINT accepted in their place.
        SIGINT is what a pexpect caller already writes for an interrupt, and
        it goes to the child as Ctrl-C written into the ConPTY rather than as
        a console control event delivered to whatever shares the child's
        process group; one spelling for one behaviour is worth more than three
        spellings for two. SIGTERM is TerminateProcess, deliberately.
        """
        if sig not in (signal.SIGTERM, signal.SIGINT):
            msg = f"kill() cannot deliver signal {sig} on Windows"
            raise PtyProcessError(msg)
        if sig == signal.SIGINT:
            self.sendintr()
            return
        with _as_ptyproc_err():
            os.kill(self.pid, signal.SIGTERM)

    def close(self, force: bool = True) -> None:
        """Close the connection to the child, terminating it if *force*."""
        if self.closed:
            return
        try:
            # winpty.PtyProcess.isalive() -- which isalive() above, and
            # pty_spawn's read loop, call constantly -- sets
            # self._proc.closed = not alive as a side effect
            # (winpty/ptyprocess.py:272). By the time a child has exited,
            # the normal case, _proc.closed is already True, and
            # _proc.close() is gated on `if not self.closed:`
            # (winpty/ptyprocess.py:144) -- so without this reset it would
            # return immediately without closing fileobj or _server, leaking
            # two sockets and the reader thread until GC finalizes them and
            # raises ResourceWarning, which filterwarnings = ["error"] would
            # turn into a failure somewhere unrelated.
            self._proc.closed = False
            with _as_ptyproc_err():
                self._proc.close(force=force)
        finally:
            self.fd = -1
        self.isalive()
