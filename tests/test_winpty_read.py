"""The Windows backend's read path, exercised where there is no ConPTY.

``src/pexpect/_winpty.py`` needs a real console for almost everything it does,
and so cannot be tested anywhere but on Windows -- except here. Its read path
does not touch ConPTY at all: pywinpty's reader thread pumps the child's output
into a loopback socket, and ``read_bytes()`` reads that socket. A scripted
stand-in for it is enough to pin the whole of what that method has to get
right, on any platform:

* pywinpty's ``b'0011Ignore'`` sentinel is stripped whatever size the caller
  asked for, including the ``size=1`` that ``read_nonblocking`` defaults to
  and ``pexpect.pxssh`` reads in a loop;
* a sentinel split across two socket reads is held back rather than
  half-delivered;
* the end-of-file contract ``SpawnBase.read_nonblocking``'s BSD-style arm
  depends on -- an empty read means ``flag_eof`` and ``b""`` -- is unchanged,
  and is not reported while buffered output is still undelivered;
* an abortive socket close reads as end of file, and any other socket error as
  a backend error rather than as a raw ``OSError`` out of ``expect()``;
* a withheld tail that nothing is going to complete is handed over instead of
  blocking in ``recv()``, which on a real socket would hang without bound.

The sentinel literal below is ``winpty/ptyprocess.py:353``'s, written out
rather than imported from the module under test, so that this file says what
pywinpty does instead of agreeing with what pexpect believes about it.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections import deque
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import pexpect

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

# winpty/ptyprocess.py:353: `data = pty.read(blocking=blocking) or '0011Ignore'`,
# sent as UTF-8 on the line below it. Ten bytes, which is why a one-byte read
# cannot recognise them.
_SENTINEL = b"0011Ignore"


class _WinptyError(Exception):
    """Stands in for winpty.WinptyError, which is also a plain Exception."""


# Every stand-in socket made during a test, so the fixture below can close the
# pipe each one keeps. A module-level list rather than a factory fixture so
# that the helper stays callable as _child(backend, ...) from any test.
_OPEN: list[_Socket] = []


class _Socket:
    """The loopback socket pywinpty's reader thread writes the child into.

    ``recv()`` hands back at most *size* bytes and never crosses one of the
    scripted sends. That is the conservative half of what a stream socket may
    do -- the kernel is also free to coalesce two sends into one read, which a
    script that wants that writes as a single chunk.

    A real pipe stands behind ``fileno()`` so that the ``select()`` in
    ``_socket_readable()`` is the real one, answering about a real descriptor:
    one byte is parked in the pipe for each chunk still to be handed out, plus
    one for the close, and each ``recv()`` that finishes a chunk takes its byte
    back out. So "readable" means "there is more coming", which is what the
    kernel would say of the real socket.

    *closes* is what happens when the script runs out. True is the reader
    thread's FIN -- an empty read, and end of file. False is a child that is
    simply quiet: a real blocking socket would sit in ``recv()`` forever, and
    the ``BlockingIOError`` here is how that shows up as a failing test rather
    than as a hung one.
    """

    def __init__(self, chunks: Sequence[bytes], *, closes: bool = True) -> None:
        """Script the sends the reader thread is to have made."""
        self.chunks = deque(chunks)
        self.sizes: list[int] = []
        self.error: OSError | None = None
        self.closes = closes
        self._read_fd, self._write_fd = os.pipe()
        os.write(self._write_fd, b"." * (len(self.chunks) + int(closes)))
        _OPEN.append(self)

    def close(self) -> None:
        """Release the pipe behind fileno()."""
        os.close(self._read_fd)
        os.close(self._write_fd)

    def fileno(self) -> int:
        """Return the descriptor select() is to answer about."""
        return self._read_fd

    def recv(self, size: int) -> bytes:
        """Return up to *size* bytes, or b"" once the script has closed."""
        self.sizes.append(size)
        if self.error is not None:
            raise self.error
        if not self.chunks:
            if not self.closes:
                msg = "recv() would block; a real socket would hang here"
                raise BlockingIOError(msg)
            # The FIN the reader thread's `client.close()` sends once
            # pty.iseof() is true, which is what end of file looks like here.
            os.read(self._read_fd, 1)
            return b""
        head = self.chunks.popleft()
        if len(head) > size:
            # Part of a chunk is left, so its readability marker stays put.
            self.chunks.appendleft(head[size:])
            return head[:size]
        os.read(self._read_fd, 1)
        return head


@pytest.fixture(autouse=True)
def _closed_stand_in_sockets() -> Iterator[None]:
    """Close the pipes the stand-ins keep, so no test leaks descriptors."""
    yield
    while _OPEN:
        _OPEN.pop().close()


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Load ``src/pexpect/_winpty.py`` with a stand-in for pywinpty.

    The module imports ``winpty`` at import time and that package cannot be
    installed here, so something has to answer for it. Executing the file
    under a private name rather than as ``pexpect._winpty`` also keeps the
    half-faked module out of ``sys.modules`` for the rest of the session.
    """
    fake = ModuleType("winpty")
    fake.WinptyError = _WinptyError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "winpty", fake)
    path = Path(pexpect.__file__).parent / "_winpty.py"
    spec = importlib.util.spec_from_file_location("pexpect_winpty_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _child(
    backend: ModuleType,
    *chunks: bytes,
    closes: bool = True,
    write: Callable[[str], int] | None = None,
) -> Any:  # noqa: ANN401
    """Return the backend over a socket that sends *chunks* and then closes.

    The pid and fd are the two attributes ``__init__`` copies off the pywinpty
    process; nothing in the read path looks at either. *write* stands in for
    winpty.PtyProcess.write(), whose return value is the only thing the write
    path cannot reason about from the source -- see the tests that use it.
    """
    proc = SimpleNamespace(
        fileobj=_Socket(chunks, closes=closes),
        pid=4321,
        fd=7,
        write=write,
    )
    return backend.PtyProcess(proc)


def test_the_sentinel_never_reaches_a_one_byte_read(backend: ModuleType) -> None:
    """A size=1 read gets the child's bytes, not the sentinel's first byte.

    This is the case a plain ``recv(size)`` gets wrong: the sentinel is ten
    bytes, ``bytes.replace`` on a one-byte chunk finds nothing to strip, and
    b"0" goes to the caller as though the child had printed it.
    """
    child = _child(backend, _SENTINEL + b"hi")
    assert child.read_bytes(1) == b"h"
    assert child.read_bytes(1) == b"i"
    assert child.read_bytes(1) == b""
    assert child.flag_eof
    # Whatever the caller asked for, the socket was asked for enough bytes to
    # recognise the sentinel at all.
    assert all(size >= len(_SENTINEL) for size in child._proc.fileobj.sizes)


def test_a_sentinel_split_across_two_reads_is_never_half_delivered(
    backend: ModuleType,
) -> None:
    """Bytes that are still a possible sentinel are held back, not returned."""
    child = _child(backend, b"0011Ig", b"nore", b"data")
    assert child.read_bytes(1024) == b"data"


def test_a_sentinel_coalesced_with_real_output_is_stripped(backend: ModuleType) -> None:
    """The sentinel is found by search, not by comparing the whole chunk."""
    child = _child(backend, b"before" + _SENTINEL + b"after")
    assert child.read_bytes(1024) == b"beforeafter"


def test_a_partial_sentinel_at_end_of_file_is_the_childs_own_output(
    backend: ModuleType,
) -> None:
    """Held-back bytes are delivered once nothing can arrive to complete them.

    A child whose last output is "001" has printed three characters that look
    like the start of a sentinel. Once the socket closes they cannot become
    one, so they are the child's, and end of file waits until they have been
    handed over.
    """
    child = _child(backend, b"001")
    assert child.read_bytes(1024) == b"001"
    assert not child.flag_eof
    assert child.read_bytes(1024) == b""
    assert child.flag_eof


def test_an_empty_socket_read_is_end_of_file(backend: ModuleType) -> None:
    """The contract SpawnBase.read_nonblocking's BSD-style arm turns into EOF."""
    child = _child(backend)
    assert child.read_bytes(1024) == b""
    assert child.flag_eof


def test_buffered_output_is_reported_as_pending(backend: ModuleType) -> None:
    """What the read held back is visible to pty_spawn's readiness check.

    Reading ahead of the caller's size puts bytes somewhere ``select()`` on
    the descriptor cannot see them, so without ``pending()`` the next
    ``read_nonblocking`` would wait out its timeout for data already in hand.
    """
    child = _child(backend, b"hello")
    assert not child.pending()
    assert child.read_bytes(1) == b"h"
    assert child.pending()
    assert child.read_bytes(1024) == b"ello"
    assert not child.pending()


def test_a_withheld_tail_is_delivered_rather_than_waited_on(backend: ModuleType) -> None:
    """A quiet child must not leave read_bytes() blocked in recv() forever.

    b"0" is a proper prefix of the sentinel, so it is withheld -- and the
    child that wrote it is now waiting for input, so the socket stays empty.
    Looping for more data here is a blocking recv() that never returns: an
    unbounded hang, in the one library whose whole point is that reads have
    timeouts. It is not an exotic path either, since ConPTY echo is always on
    and a caller's own send("0") comes back as a one-byte chunk.
    """
    child = _child(backend, b"0", closes=False)
    assert child.read_bytes(1024) == b"0"
    assert not child.flag_eof


def test_a_withheld_tail_grown_by_a_later_chunk_is_still_delivered(
    backend: ModuleType,
) -> None:
    """The same, when more output arrived and still did not settle it.

    b"0" is withheld, b"011" completes b"0011" -- four bytes that are still a
    possible sentinel -- and then the child goes quiet again. The poll has to
    happen on every turn of the loop, not just the first.
    """
    child = _child(backend, b"0", b"011", closes=False)
    assert child.read_bytes(1024) == b"0011"
    assert not child.flag_eof


def test_a_quiet_child_with_a_withheld_tail_is_reported_as_pending(
    backend: ModuleType,
) -> None:
    """Readiness agrees with the read, so expect() does not wait for nothing.

    A size-limited read is what leaves the buffer holding nothing but a
    withheld tail: b"ab0" read one byte at a time gets through b"a" and b"b"
    and stops. If pending() said no there, while read_bytes() would hand the
    b"0" over, pty_spawn._ready() would fall through to select(), find the
    drained socket, and time out holding a byte it already has.
    """
    child = _child(backend, b"ab0", closes=False)
    assert child.read_bytes(1) == b"a"
    assert child.read_bytes(1) == b"b"
    assert child.pending()
    assert child.read_bytes(1) == b"0"
    assert not child.pending()


def test_an_abortive_close_is_read_as_end_of_file(backend: ModuleType) -> None:
    """A reset connection means the same thing as the orderly FIN.

    An abortive close of the loopback socket is one of the ways a child exit
    can present on Windows. Reported as an error it would come out of
    expect() as an exception; read as end of file it is what every pexpect
    caller already handles.
    """
    child = _child(backend)
    child._proc.fileobj.error = ConnectionResetError(
        10054, "An existing connection was forcibly closed by the remote host"
    )
    assert child.read_bytes(1024) == b""
    assert child.flag_eof


def test_any_other_socket_error_becomes_a_backend_error(backend: ModuleType) -> None:
    """A socket failure that is not an end of file is still pexpect's own type.

    WinError 10038 on a handle that has been closed is the example. Left as a
    raw OSError it would escape expect() unrecognised, because SpawnBase's
    read_nonblocking translates only errno EIO.
    """
    child = _child(backend)
    child._proc.fileobj.error = OSError(
        10038, "An operation was attempted on something that is not a socket"
    )
    with pytest.raises(backend.PtyProcessError, match="not a socket"):
        child.read_bytes(1024)
    assert not child.flag_eof


def test_a_short_write_is_reported_rather_than_lost(backend: ModuleType) -> None:
    """A write the backend did not take in full must not be reported as one.

    send() returns a byte count its caller is entitled to believe, and
    pexpect has no resend: a short write reported as a complete one loses the
    remainder silently.
    """
    child = _child(backend, write=lambda text: len(text) - 1)
    with pytest.raises(backend.PtyProcessError, match="4 units written for 5 characters"):
        child.write_bytes(b"hello")


def test_a_write_counted_in_a_wider_unit_is_not_short(backend: ModuleType) -> None:
    """Non-ASCII must not be mistaken for a short write.

    pywinpty declares PTY.write() as returning an int and documents no unit
    for it; the check is against the character count for that reason, since
    every candidate encoding spends at least one unit per character. Here the
    stand-in counts UTF-8 bytes, so it returns six for five characters.
    """
    child = _child(backend, write=lambda text: len(text.encode()))
    payload = "h\u00e9llo".encode()
    assert child.write_bytes(payload) == len(payload)


def test_bytes_that_are_not_utf8_are_refused(backend: ModuleType) -> None:
    """The payload cannot survive pywinpty's str parameter, so it is refused.

    PTY.write() takes a Rust str by way of PyUnicode_AsUTF8AndSize with
    surrogatepass, which either rejects a lone surrogate or re-encodes it as
    three-byte WTF-8. Refusing up front beats a bare UnicodeEncodeError from
    inside the dependency or silent corruption on the wire.
    """
    child = _child(backend, write=len)
    with pytest.raises(backend.PtyProcessError, match="non-UTF-8"):
        child.write_bytes(b"\xff")
