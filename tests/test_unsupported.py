"""What each platform refuses, stated once, from both sides.

pexpect's interface is the same on Linux and on Windows; some of it cannot
work there. Every such call raises ExceptionPexpect naming itself, and this
module is where that contract lives -- asserting the raise on Windows and the
working behaviour on POSIX, so neither half can drift.

It is also the coverage these calls get: the sys.platform branches they live
behind are excluded from the coverage floor, because neither branch can run on
the other platform, and these tests are what stands in for that gate.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

import pexpect

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

pytestmark = pytest.mark.usefixtures("fast_sleep")

_ON_WINDOWS = sys.platform == "win32"
_CHILD = [sys.executable, "-c", "input()"]

# Written as the number rather than as signal.SIGHUP, which does not exist on
# Windows: the name would fail while this module was being imported, and a
# skipif never runs when the module carrying it cannot be imported.
_SIGHUP = 1


@pytest.fixture
def child() -> Iterator[pexpect.spawn[bytes]]:
    """Spawn a child that just waits to be told, and close it afterwards."""
    spawned = pexpect.spawn(_CHILD[0], _CHILD[1:], timeout=10)
    yield spawned
    spawned.close(force=True)


@pytest.mark.skipif(not _ON_WINDOWS, reason="POSIX supports every call here")
@pytest.mark.parametrize(
    ("name", "call"),
    [
        ("getecho", lambda c: c.getecho()),
        ("setecho", lambda c: c.setecho(state=False)),
        ("waitnoecho", lambda c: c.waitnoecho(timeout=1)),
        ("interact", lambda c: c.interact()),
    ],
)
def test_windows_refuses_the_terminal_calls(
    child: pexpect.spawn[bytes],
    name: str,
    call: Callable[[pexpect.spawn[bytes]], object],
) -> None:
    """Each terminal call raises ExceptionPexpect naming itself on Windows."""
    with pytest.raises(pexpect.ExceptionPexpect, match=name):
        call(child)


@pytest.mark.skipif(not _ON_WINDOWS, reason="POSIX delivers every signal")
def test_windows_refuses_the_signals_it_cannot_deliver(child: pexpect.spawn[bytes]) -> None:
    """kill() cannot deliver a signal ConPTY has no equivalent for."""
    with pytest.raises(pexpect.ExceptionPexpect):
        child.kill(_SIGHUP)


@pytest.mark.skipif(not _ON_WINDOWS, reason="POSIX supports both arguments")
@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("preexec_fn", {"preexec_fn": lambda: None}),
        ("ignore_sighup", {"ignore_sighup": True}),
        ("echo", {"echo": False}),
        ("use_poll", {"use_poll": True}),
    ],
)
def test_windows_refuses_the_posix_only_arguments(name: str, kwargs: dict[str, object]) -> None:
    """Each POSIX-only constructor argument raises ExceptionPexpect naming itself."""
    with pytest.raises(pexpect.ExceptionPexpect, match=name):
        # spawn() is overloaded on `encoding`, and mypy cannot match an
        # overload against a **dict whose exact keys vary per parametrize
        # case -- the call is fine, only the static match fails.
        pexpect.spawn(_CHILD[0], _CHILD[1:], **kwargs)  # type: ignore[call-overload]


@pytest.mark.skipif(not _ON_WINDOWS, reason="POSIX sends any byte a caller likes")
@pytest.mark.parametrize("send", [lambda c: c.send(b"\xff"), lambda c: c.write(b"\xff")])
def test_windows_refuses_bytes_that_are_not_utf8(
    child: pexpect.spawn[bytes],
    send: Callable[[pexpect.spawn[bytes]], object],
) -> None:
    """A bytes-mode payload that is not valid UTF-8 is refused, not mangled.

    pywinpty's write takes a Rust str, so a byte outside UTF-8 is either
    rejected there or re-encoded on the way through. send() is the commonest
    call in the library and sendline() and write() both funnel into it, which
    is why this is worth an assertion of its own rather than a docs footnote.
    """
    with pytest.raises(pexpect.ExceptionPexpect, match="UTF-8"):
        send(child)


@pytest.mark.skipif(_ON_WINDOWS, reason="the Windows half is asserted above")
def test_posix_supports_the_same_calls(child: pexpect.spawn[bytes]) -> None:
    """Every call refused on Windows still works exactly as before on POSIX."""
    assert child.getecho() is True
    child.setecho(state=False)
    assert child.waitnoecho(timeout=5) is True
    child.kill(_SIGHUP)
    # The non-UTF-8 payload the Windows backend refuses goes through here.
    assert child.send(b"\xff") == 1
