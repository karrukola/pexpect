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
socket it already exposes gives the child's real bytes instead.

Two properties of the dependency are inherited rather than fixed, recorded here
so they are not rediscovered as pexpect bugs: each spawn opens a listening
socket on 127.0.0.1, which a local process could race the connect on; and its
reader sends the in-band sentinel b'0011Ignore' for an empty read and strips it
again, so a child printing that exact string loses it. PYWINPTY_BLOCK defaults
to 1, which makes an empty read, and so the sentinel, rare.
"""

from __future__ import annotations

import os
import signal
import time
from typing import TYPE_CHECKING

import winpty

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class PtyProcessError(Exception):
    """Raised for a backend failure, and for a call Windows cannot honour.

    pty_spawn turns this into ExceptionPexpect through _wrap_ptyprocess_err,
    which is how an unsupported call reaches the caller as the one exception
    type pexpect raises.
    """


class PtyProcess:
    """A child running in a ConPTY, presented as pexpect's pty backend."""

    def __init__(self, proc: winpty.PtyProcess) -> None:
        self._proc = proc
        self.pid: int = proc.pid
        self.fd: int = proc.fd
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
        try:
            proc = winpty.PtyProcess.spawn(decoded, cwd=cwd, env=env, dimensions=dimensions)
        except (winpty.WinptyError, OSError) as e:
            raise PtyProcessError(*e.args) from e
        return cls(proc)

    def read_bytes(self, size: int) -> bytes:
        """Read at most *size* bytes of the child's output.

        Reads the socket pywinpty's reader thread feeds, so the bytes are the
        child's own. An empty read is end of file, which is what
        SpawnBase.read_nonblocking's BSD-style arm turns into pexpect's EOF.
        """
        data: bytes = self._proc.fileobj.recv(size)
        if not data:
            self.flag_eof = True
        return data

    def write_bytes(self, data: bytes) -> int:
        """Write *data* to the child and return the number of bytes taken."""
        # winpty.PTY.write takes str and encodes UTF-8 itself; surrogateescape
        # is what carries bytes that are not valid UTF-8 through unchanged.
        return int(self._proc.write(data.decode("utf-8", "surrogateescape")))

    def isatty(self) -> bool:
        """Return True: a ConPTY child is always attached to a console."""
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
        """Return the console size as (rows, cols)."""
        rows, cols = self._proc.getwinsize()
        return rows, cols

    def setwinsize(self, rows: int, cols: int) -> None:
        """Resize the ConPTY."""
        self._proc.setwinsize(rows, cols)

    def isalive(self) -> bool:
        """Whether the child is still running, reaping it if it is not."""
        if self._proc.isalive():
            return True
        self._reap()
        return False

    def wait(self) -> int | None:
        """Block until the child exits and return its exit status."""
        self._proc.wait()
        self._reap()
        return self.exitstatus

    def _reap(self) -> None:
        """Record the exit status once, the way ptyprocess's isalive() does."""
        if not self.terminated:
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
        self.sendintr()
        time.sleep(self.delayafterterminate)
        if not self.isalive():
            return True
        if force:
            self.kill(signal.SIGTERM)
            time.sleep(self.delayafterterminate)
            return not self.isalive()
        return False

    def kill(self, sig: int) -> None:
        """Send *sig* to the child, for the two signals Windows can deliver.

        os.kill() on Windows delivers CTRL_C_EVENT and CTRL_BREAK_EVENT through
        GenerateConsoleCtrlEvent and treats every other value as a
        TerminateProcess exit code, so a SIGHUP here would terminate the child
        rather than hang it up. Refusing is the honest answer; the caller who
        wants an interrupt has sendintr().
        """
        if sig not in (signal.SIGTERM, signal.SIGINT):
            msg = f"kill() cannot deliver signal {sig} on Windows"
            raise PtyProcessError(msg)
        if sig == signal.SIGINT:
            self.sendintr()
            return
        os.kill(self.pid, signal.SIGTERM)

    def close(self, force: bool = True) -> None:
        """Close the connection to the child, terminating it if *force*."""
        if self.closed:
            return
        try:
            self._proc.close(force=force)
        except (winpty.WinptyError, OSError) as e:
            raise PtyProcessError(*e.args) from e
        finally:
            self.fd = -1
        self.isalive()
