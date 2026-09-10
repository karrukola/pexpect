"""The shortest end-to-end statement: a child starts, talks, and exits.

Every other spawn test builds on this, and on Windows this is the first code
that drives a ConPTY, so when the platform is broken this is the test that says
so in one line rather than in four hundred.
"""

from __future__ import annotations

import sys

import pytest

import pexpect

pytestmark = pytest.mark.usefixtures("fast_sleep")

# Its own interpreter, so the test needs no program the platform may not have.
_GREETER = [sys.executable, "-c", "print('hello ' + input())"]


def test_the_public_names_exist() -> None:
    """The bug report's exact symptom: these must not be AttributeError."""
    for name in ("spawn", "spawnu", "run", "runu"):
        assert hasattr(pexpect, name), f"pexpect.{name} is missing on {sys.platform}"


def test_a_child_answers() -> None:
    """A child starts, reads a line, writes a reply, and exits cleanly."""
    child = pexpect.spawn(_GREETER[0], _GREETER[1:], timeout=10, encoding="utf-8")
    try:
        child.sendline("world")
        child.expect("hello world")
        child.expect(pexpect.EOF)
    finally:
        child.close(force=True)
    assert child.exitstatus == 0


def test_a_child_reports_its_window_size() -> None:
    """The dimensions given at spawn time round-trip through get/setwinsize."""
    child = pexpect.spawn(_GREETER[0], _GREETER[1:], dimensions=(40, 100))
    try:
        assert child.getwinsize() == (40, 100)
        child.setwinsize(24, 80)
        assert child.getwinsize() == (24, 80)
    finally:
        child.close(force=True)


def test_fileno_is_a_descriptor() -> None:
    """fileno() returns a real, non-negative descriptor the caller can select() on."""
    child = pexpect.spawn(_GREETER[0], _GREETER[1:])
    try:
        assert isinstance(child.fileno(), int)
        assert child.fileno() >= 0
    finally:
        child.close(force=True)


def test_terminate_stops_a_child_that_ignores_nothing() -> None:
    """terminate(force=True) works its way up to a child that never dies on its own."""
    child = pexpect.spawn(sys.executable, ["-c", "input()"], timeout=10)
    try:
        assert child.isalive()
        assert child.terminate(force=True) is True
        assert child.isalive() is False
    finally:
        child.close(force=True)


def test_terminate_on_a_dead_child_is_true() -> None:
    """terminate() on a child that already exited reports success, not an error."""
    child = pexpect.spawn(sys.executable, ["-c", ""], timeout=10)
    try:
        child.expect(pexpect.EOF)
        assert child.terminate() is True
    finally:
        child.close(force=True)
