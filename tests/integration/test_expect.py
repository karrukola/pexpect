"""Tests for pattern preference in expect(), driven by a Python child.

Each of these starts one or two Python interpreters, and the REPL tests then
walk five statements through one. That is above the suite's time budget before
pexpect does anything, so they live here.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

import pytest

import pexpect
from tests import pexpect_test_case

if TYPE_CHECKING:
    from collections.abc import Callable

    from pexpect.spawnbase import _Pattern

    # The bound expect() or expect_exact() method of a spawn, as the helpers
    # below call it: one pattern or a list of them in, the matching index out.
    _Matcher = Callable[[_Pattern | list[_Pattern]], int]

pytestmark = pytest.mark.usefixtures("fast_sleep", "lean_child_env")


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for which of several overlapping patterns expect() returns."""

    def _greed(self, expect: _Matcher) -> None:
        # End at the same point: the one with the earliest start should win
        assert expect([b"3, 4", b"2, 3, 4"]) == 1

        # Start at the same point: first pattern passed wins
        assert expect([b"5,", b"5, 6"]) == 0

        # Same pattern passed twice: first instance wins
        assert expect([b"7, 8", b"7, 8, 9", b"7, 8"]) == 0

    def _greed_read1(self, expect: _Matcher) -> None:
        # Here, one has an earlier start and a later end. When processing
        # one character at a time, the one that finishes first should win,
        # because we don't know about the other match when it wins.
        # If maxread > 1, this behaviour is currently undefined, although in
        # most cases the one that starts first will win.
        assert expect([b"1, 2, 3", b"2,"]) == 1

    def test_greed(self) -> None:
        """Check which of several overlapping patterns expect() prefers."""
        p = pexpect.spawn(self.PYTHONBIN + " list100.py")
        self._greed(p.expect)

        p = pexpect.spawn(self.PYTHONBIN + " list100.py", maxread=1)
        self._greed_read1(p.expect)

    def test_greed_exact(self) -> None:
        """Like test_greed(), but for expect_exact()."""
        p = pexpect.spawn(self.PYTHONBIN + " list100.py")
        self._greed(p.expect_exact)

        p = pexpect.spawn(self.PYTHONBIN + " list100.py", maxread=1)
        self._greed_read1(p.expect_exact)

    def _ordering(self, p: pexpect.spawn[bytes], expect: _Matcher) -> None:
        p.timeout = 20
        # Five sendlines, each of which the REPL answers before the next one is
        # sent, so the send delay only paces what expect() already paces.
        p.delaybeforesend = None
        expect(b">>> ")

        p.sendline("list(range(4*3))")
        assert expect([b"5,", b"5,"]) == 0
        expect(b">>> ")

        p.sendline(b"list(range(4*3))")
        assert expect([b"7,", b"5,"]) == 1
        expect(b">>> ")

        p.sendline(b"list(range(4*3))")
        assert expect([b"5,", b"7,"]) == 0
        expect(b">>> ")

        p.sendline(b"list(range(4*5))")
        assert expect([b"2,", b"12,"]) == 0
        expect(b">>> ")

        p.sendline(b"list(range(4*5))")
        assert expect([b"12,", b"2,"]) == 1

    def test_ordering(self) -> None:
        """Check which pattern expect() returns when many may eventually match.

        I (Grahn) am a bit confused about what should happen, but this test
        passes with pexpect 2.1.
        """
        p = pexpect.spawn(self.PYTHONBIN)
        self._ordering(p, p.expect)

    def test_ordering_exact(self) -> None:
        """Check which pattern expect_exact() returns when many may match.

        I (Grahn) am a bit confused about what should happen, but this test
        passes for the expect() method with pexpect 2.1.
        """
        p = pexpect.spawn(self.PYTHONBIN)
        # drive the helper with expect_exact() instead
        self._ordering(p, p.expect_exact)


if __name__ == "__main__":
    unittest.main()
