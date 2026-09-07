"""Tests for :meth:`pexpect.spawn.waitnoecho`.

This is the one test in the suite that measures a wall clock, and it has to: it
asserts that the parent waited for something a child process did. The suite's
``fast_sleep`` fixture only reaches the parent's clock, because ``spawn`` execs
the child and no monkeypatching survives an exec. Faking one side of that pair
makes the comparison meaningless, so this module does not ask for that fixture
and scales the delays down instead, to the smallest ones ``waitnoecho`` can
still resolve: it polls ``getecho()`` every 100 ms.

The wall clock alone cannot tell a wait apart from a slow start, so the poll
sleeps are counted too.
"""

from __future__ import annotations

import sys
import time
import unittest
from unittest import mock

import pytest

import pexpect
from tests import pexpect_test_case

pytestmark = pytest.mark.usefixtures("sleep_spy")

# Passed to tests/echo_wait.py: it turns ECHO off this long after it starts, and
# leaves it off for _ECHO_STAYS_OFF. The first has to exceed waitnoecho's 100 ms
# poll interval, or there would be nothing to wait for.
_ECHO_OFF_AFTER = 0.15
_ECHO_STAYS_OFF = 1.0

# Timeout for the child that does turn ECHO off. Only a ceiling: the wait ends
# when the child acts, well inside it.
_WAIT_TIMEOUT = 1.0

# Timeout for a `cat`, which never turns ECHO off, so the whole of it is spent.
_NEVER_OFF_TIMEOUT = 0.3

# waitnoecho sleeps once per poll, so the sleep count is how many times it
# looked. Both numbers below are the smallest the delays above guarantee.
_MIN_POLLS_BEFORE_ECHO_OFF = 1
_MIN_POLLS_BEFORE_GIVING_UP = 2


@pytest.fixture
def sleep_spy(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Count the sleeps pexpect makes, without shortening any of them.

    Note what this module does *not* ask for: ``fast_sleep``. The sleeps counted
    here are the real thing, so that the clock the assertions read runs at the
    same rate as the child's.
    """
    spy = mock.Mock(wraps=time.sleep)
    monkeypatch.setattr(time, "sleep", spy)
    request.instance.sleeps = spy


class WaitNoEchoTestCase(pexpect_test_case.PexpectTestCase):
    """Tests that waitnoecho waits for the child, and gives up when it must."""

    def echo_wait(self) -> pexpect.spawn:
        """Spawn the helper that turns ECHO off partway through its run."""
        return pexpect.spawn(f"{self.PYTHONBIN} echo_wait.py {_ECHO_OFF_AFTER} {_ECHO_STAYS_OFF}")

    def test_waits_for_the_child_to_turn_echo_off(self) -> None:
        """Wait on a child process to set echo mode.

        For example, this tests that we could wait for SSH to set ECHO False
        when asking of a password. This makes use of an external script
        echo_wait.py.
        """
        child = self.echo_wait()
        start = time.time()
        try:
            found = child.waitnoecho(timeout=_WAIT_TIMEOUT)
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise
        elapsed = time.time() - start

        assert found, "waitnoecho gave up before ECHO was set off."
        assert self.sleeps.call_count >= _MIN_POLLS_BEFORE_ECHO_OFF, (
            "waitnoecho returned without waiting for the child."
        )
        assert elapsed < _WAIT_TIMEOUT, "waitnoecho took longer than its timeout."

    def test_gives_up_when_echo_never_goes_off(self) -> None:
        """Return False after the whole timeout when ECHO is never set off."""
        child = pexpect.spawn("cat")
        start = time.time()
        found = child.waitnoecho(timeout=_NEVER_OFF_TIMEOUT)
        elapsed = time.time() - start

        assert not found, f"retval should be False, retval={found}"
        assert self.sleeps.call_count >= _MIN_POLLS_BEFORE_GIVING_UP, (
            "waitnoecho gave up without polling for the whole timeout."
        )
        assert elapsed >= _NEVER_OFF_TIMEOUT, (
            "waitnoecho should have waited for its whole timeout."
        )

    def test_waits_with_the_default_timeout(self) -> None:
        """Take the timeout from the spawn when waitnoecho is given none."""
        child = self.echo_wait()
        start = time.time()

        assert child.waitnoecho()
        assert time.time() - start < child.timeout


if __name__ == "__main__":
    unittest.main()
