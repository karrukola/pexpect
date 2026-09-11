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
  a backend error rather than as a raw ``OSError`` out of ``expect()``.

The sentinel literal below is ``winpty/ptyprocess.py:353``'s, written out
rather than imported from the module under test, so that this file says what
pywinpty does instead of agreeing with what pexpect believes about it.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import deque
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import pexpect

if TYPE_CHECKING:
    from collections.abc import Sequence

# winpty/ptyprocess.py:353: `data = pty.read(blocking=blocking) or '0011Ignore'`,
# sent as UTF-8 on the line below it. Ten bytes, which is why a one-byte read
# cannot recognise them.
_SENTINEL = b"0011Ignore"


class _WinptyError(Exception):
    """Stands in for winpty.WinptyError, which is also a plain Exception."""


class _Socket:
    """The loopback socket pywinpty's reader thread writes the child into.

    ``recv()`` hands back at most *size* bytes and never crosses one of the
    scripted sends. That is the conservative half of what a stream socket may
    do -- the kernel is also free to coalesce two sends into one read, which a
    script that wants that writes as a single chunk.
    """

    def __init__(self, chunks: Sequence[bytes]) -> None:
        """Script the sends the reader thread is to have made."""
        self.chunks = deque(chunks)
        self.sizes: list[int] = []
        self.error: OSError | None = None

    def recv(self, size: int) -> bytes:
        """Return up to *size* bytes, or b"" once the script has run out."""
        self.sizes.append(size)
        if self.error is not None:
            raise self.error
        if not self.chunks:
            # The FIN the reader thread's `client.close()` sends once
            # pty.iseof() is true, which is what end of file looks like here.
            return b""
        head = self.chunks.popleft()
        if len(head) > size:
            self.chunks.appendleft(head[size:])
            return head[:size]
        return head


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


def _child(backend: ModuleType, *chunks: bytes) -> Any:  # noqa: ANN401
    """Return the backend reading a socket that sends *chunks* and then closes.

    The pid and fd are the two attributes ``__init__`` copies off the pywinpty
    process; nothing in the read path looks at either.
    """
    proc = SimpleNamespace(fileobj=_Socket(chunks), pid=4321, fd=7)
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
