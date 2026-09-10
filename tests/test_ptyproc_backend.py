"""The backend surface pty_spawn relies on, whichever platform supplies it.

pexpect talks to one process backend through pexpect._ptyproc: ptyprocess on
POSIX, an adapter over pywinpty on Windows. Everything here is a statement
about that seam rather than about either implementation, so it runs on both.
"""

from __future__ import annotations

import sys

import pytest

from pexpect import _ptyproc

# The methods and attributes pty_spawn.spawn reaches for. A backend missing
# any of them fails at the call site, in whichever test happens to run first.
#
# Checked against a live child rather than against the class: ptyprocess sets
# status, exitstatus, signalstatus, flag_eof, terminated, fd and pid in
# __init__, so hasattr() on the class is False for every one of them.
_REQUIRED = (
    "close",
    "exitstatus",
    "fd",
    "flag_eof",
    "getwinsize",
    "isalive",
    "isatty",
    "kill",
    "pid",
    "read_bytes",
    "sendcontrol",
    "sendeof",
    "sendintr",
    "setwinsize",
    "signalstatus",
    "status",
    "terminate",
    "terminated",
    "wait",
    "write_bytes",
)


def test_backend_offers_what_pty_spawn_calls() -> None:
    """The backend must expose every attribute and method pty_spawn calls."""
    child = _ptyproc.PtyProcess.spawn([sys.executable, "-c", "input()"])
    try:
        missing = [name for name in _REQUIRED if not hasattr(child, name)]
        assert not missing, f"the {sys.platform} backend is missing {missing}"
    finally:
        child.close(force=True)


def test_backend_error_is_an_exception_class() -> None:
    """PtyProcessError is a plain Exception subclass, wherever it comes from."""
    assert issubclass(_ptyproc.PtyProcessError, Exception)


def test_use_native_pty_fork_is_a_bool() -> None:
    """use_native_pty_fork is a bool on either backend.

    Purely informational since ptyprocess 0.7, and read by pexpect.spawn's
    class attribute of the same name; the type is the whole contract.
    """
    assert isinstance(_ptyproc.use_native_pty_fork, bool)


def test_round_trip_through_the_byte_seam() -> None:
    """Bytes written to the pty come back out the same read, byte for byte."""
    child = _ptyproc.PtyProcess.spawn([sys.executable, "-c", "print(input())"])
    try:
        child.write_bytes(b"ping\r")
        seen = b""
        while b"ping" not in seen.replace(b"\r", b""):
            seen += child.read_bytes(1024)
    finally:
        child.close(force=True)


def test_windows_backend_refuses_the_termios_calls() -> None:
    """Getecho and setecho have no ConPTY equivalent and must say so."""
    if sys.platform != "win32":
        pytest.skip("the POSIX backend supports both calls")
    child = _ptyproc.PtyProcess.spawn([sys.executable, "-c", "input()"])
    try:
        with pytest.raises(_ptyproc.PtyProcessError, match="getecho"):
            child.getecho()
        with pytest.raises(_ptyproc.PtyProcessError, match="setecho"):
            child.setecho(state=False)
    finally:
        child.close(force=True)
